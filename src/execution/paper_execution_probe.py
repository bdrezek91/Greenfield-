"""Disabled-by-default execution-quality probe on Bybit Demo (virtual funds).

This is **not** a strategy. It has no signal, no edge estimate, and its
entries are forced, not decided by any research candidate. Its only job is
to generate real Bybit Demo execution evidence - maker fill probability,
taker execution, spread paid/captured, slippage, order latency, partial
fills, adverse selection, and post-fill markouts - so that a later, separate,
offline job can call `src.execution.calibration.compute_markout_calibration`
and `compare_predicted_to_realized` against real fills instead of only the
deterministic simulator's static assumptions. Every trade this module opens
is tagged `EXECUTION_PROBE` in the durable state store and in the TCA
journal specifically so it can never be mistaken for, or silently counted
as, a naturally occurring research signal.

Reuses, unmodified, the same crash-safe primitives the rest of the Bybit
Demo stack already relies on:

- `PybitBybitDemoGateway` (host-pinned to `BYBIT_DEMO_REST_URL`, refused
  otherwise - see `__init__`);
- `PaperOrderStore` / `DemoOrderReconciler` for durable, idempotent order
  submission and exchange-authoritative reconciliation;
- `AutonomousDemoStateStore` for the one-active-lifecycle invariant, daily
  order-count/cooldown/kill-switch bookkeeping, and crash-safe phase
  recovery - pointed at its own database file, separate from any future
  qualified strategy's ledger, so probe activity never consumes or pollutes
  a real strategy's daily risk budget.

Every probe order is unconditionally reduce-only-flattened the moment any
quantity fills - there is no stop-loss, take-profit, or holding period. The
only reason a probe position exists at all is to observe one fill; markouts
up to 60s are then measured from public quotes with the exchange position
already flat, so the actual Demo exposure window is seconds, not minutes.

Sizing is a small, fixed, config-bounded USDT notional (never a fraction of
Demo equity - Bybit Demo's virtual equity here is ~$180k, and a %-of-equity
scheme intended for a future 100x/1%-margin strategy skeleton would produce
large notional per probe). `HARD_MAXIMUM_NOTIONAL_QUOTE_USD` is a
non-configurable ceiling enforced in code, not a default that can be
raised by editing a config file.
"""

from __future__ import annotations

import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import ROUND_DOWN, Decimal
from enum import StrEnum
from typing import Any, Protocol

from src.engines.contracts import SetupAction
from src.execution.bybit_demo_gateway import (
    BYBIT_DEMO_REST_URL,
    BybitDemoGateway,
    BybitPublicLinearMarketData,
    PublicLinearInstrumentSnapshot,
)
from src.execution.calibration import (
    MARKOUT_HORIZONS_SECONDS,
    PaperOrderObservation,
    TopOfBookQuote,
)
from src.execution.demo_autonomous_risk import AutonomousDemoRiskConfig
from src.execution.demo_autonomous_state import (
    AutonomousDemoStateError,
    AutonomousDemoStateStore,
    AutonomousTradePhase,
    AutonomousTradeRecord,
)
from src.execution.demo_operator import require_demo_paper_environment
from src.execution.demo_order_reconciler import (
    DemoExecutionLagError,
    DemoOrderReconciler,
    demo_order_link_id_for,
)
from src.execution.execution_probe_journal import ExecutionProbeJournal
from src.execution.intent import IntentSide
from src.execution.paper_reconciliation import PaperOrderRecord, PaperOrderState, PaperOrderStore

PROBE_CONFIRMATION_ENV_VAR = "GREENFIELD_DEMO_EXECUTION_PROBE_CONFIRMATION"
PROBE_CONFIRMATION_VALUE = "EXECUTION_EVIDENCE_ONLY"
"""Layered on top of `GREENFIELD_DEMO_ORDER_CONFIRMATION=BYBIT_DEMO_ONLY`
(required by `require_demo_paper_environment(order_submission=True)`); an
operator must set both, deliberately, before any probe order is submitted."""

EXECUTION_PROBE_CANDIDATE_ID = "EXECUTION_PROBE"
PROBE_VENUE = "bybit-demo"
PROBE_LEVERAGE = 1
"""Fixed, not configurable: the probe measures execution mechanics, not
capital efficiency, so it never uses the 100x used by a future strategy
skeleton - one less way virtual-fund margin arithmetic could surprise a
reader of the evidence."""

SYNTHETIC_RISK_BUDGET_USD = Decimal("1000")
"""A fixed, synthetic capital figure - not the account's real Demo equity -
fed to the reused `AutonomousDemoRiskConfig`/`AutonomousDemoStateStore`
daily-loss-cap machinery so `maximum_daily_loss_usd` means a real, small,
absolute USDT number regardless of how large Bybit Demo's virtual equity is."""

HARD_MAXIMUM_NOTIONAL_QUOTE_USD = Decimal("100")
"""Absolute ceiling on any single probe order's notional, enforced in code
and not raisable via `PaperExecutionProbeConfig`. Bounded well under the
250 USDT ceiling already reviewed for the manual smoke test."""

_ALLOWED_SYMBOLS = frozenset({"BTCUSDT", "ETHUSDT", "SOLUSDT"})


class ProbeOrderType(StrEnum):
    TAKER = "TAKER"
    MAKER = "MAKER"


@dataclass(frozen=True, slots=True)
class PaperExecutionProbeConfig:
    target_notional_quote_usd: Decimal = Decimal("30")
    maximum_notional_quote_usd: Decimal = Decimal("60")
    maker_fill_timeout_seconds: int = 20
    maximum_orders_per_utc_day: int = 12
    cooldown_seconds: int = 30
    maximum_daily_loss_usd: Decimal = Decimal("10")
    markout_horizons_seconds: tuple[float, ...] = MARKOUT_HORIZONS_SECONDS
    reconcile_poll_seconds: float = 1.0
    reconcile_timeout_seconds: float = 15.0
    maximum_exit_attempts: int = 5

    def __post_init__(self) -> None:
        if not self.target_notional_quote_usd.is_finite() or self.target_notional_quote_usd <= 0:
            raise ValueError("execution probe target notional must be positive")
        if (
            not self.maximum_notional_quote_usd.is_finite()
            or self.maximum_notional_quote_usd <= 0
            or self.maximum_notional_quote_usd > HARD_MAXIMUM_NOTIONAL_QUOTE_USD
        ):
            raise ValueError(
                "execution probe maximum notional must be positive and at most "
                f"{HARD_MAXIMUM_NOTIONAL_QUOTE_USD} USDT"
            )
        if self.target_notional_quote_usd > self.maximum_notional_quote_usd:
            raise ValueError("execution probe target notional cannot exceed its own maximum")
        if not 1 <= self.maker_fill_timeout_seconds <= 120:
            raise ValueError("execution probe maker fill timeout must be within [1, 120] seconds")
        if not 1 <= self.maximum_orders_per_utc_day <= 50:
            raise ValueError("execution probe daily order count must be within [1, 50]")
        if not 0 <= self.cooldown_seconds <= 3600:
            raise ValueError("execution probe cooldown must be within [0, 3600] seconds")
        if (
            not self.maximum_daily_loss_usd.is_finite()
            or self.maximum_daily_loss_usd <= 0
            or self.maximum_daily_loss_usd > Decimal("50")
        ):
            raise ValueError("execution probe daily loss cap must be positive and at most 50 USDT")
        if not self.markout_horizons_seconds or any(
            value <= 0 for value in self.markout_horizons_seconds
        ):
            raise ValueError("execution probe markout horizons must be positive")
        if not 0.1 <= self.reconcile_poll_seconds <= 5:
            raise ValueError(
                "execution probe reconcile poll interval must be within [0.1, 5] seconds"
            )
        if not 5 <= self.reconcile_timeout_seconds <= 120:
            raise ValueError("execution probe reconcile timeout must be within [5, 120] seconds")
        if not 1 <= self.maximum_exit_attempts <= 5:
            raise ValueError("execution probe exit attempts must be within [1, 5]")

    @property
    def risk_config(self) -> AutonomousDemoRiskConfig:
        return AutonomousDemoRiskConfig(
            maximum_trades_per_utc_day=self.maximum_orders_per_utc_day,
            cooldown_seconds=self.cooldown_seconds,
            maximum_daily_loss_fraction=self.maximum_daily_loss_usd / SYNTHETIC_RISK_BUDGET_USD,
        )


@dataclass(frozen=True, slots=True)
class ProbeCycleResult:
    status: str
    trade: AutonomousTradeRecord | None
    detail: str


class TopOfBookSource(Protocol):
    def get_ticker(self, symbol: str, *, category: str = "linear") -> dict[str, Any]: ...


class PaperExecutionProbeExecutor:
    def __init__(
        self,
        *,
        gateway: BybitDemoGateway,
        public_market: BybitPublicLinearMarketData,
        ticker: TopOfBookSource,
        orders: PaperOrderStore,
        state: AutonomousDemoStateStore,
        journal: ExecutionProbeJournal,
        config: PaperExecutionProbeConfig | None = None,
        clock: Callable[[], datetime] | None = None,
        sleep: Callable[[float], None] | None = None,
    ) -> None:
        if gateway.endpoint != BYBIT_DEMO_REST_URL:
            raise ValueError("execution probe must be pinned to Bybit Demo")
        self.gateway = gateway
        self.public_market = public_market
        self.ticker = ticker
        self.orders = orders
        self.state = state
        self.journal = journal
        self.config = config or PaperExecutionProbeConfig()
        self.reconciler = DemoOrderReconciler(gateway=gateway, store=orders)
        self._clock = clock or (lambda: datetime.now(UTC))
        self._sleep = sleep or time.sleep
        self._seq = 0

    def run(
        self,
        *,
        env: Mapping[str, str],
        symbol: str,
        request_id: str,
        now_utc: datetime | None = None,
        mode_override: ProbeOrderType | None = None,
        side_override: IntentSide | None = None,
    ) -> ProbeCycleResult:
        require_demo_paper_environment(env, order_submission=True)
        if env.get(PROBE_CONFIRMATION_ENV_VAR) != PROBE_CONFIRMATION_VALUE:
            raise ValueError(
                f"execution probe order submission requires {PROBE_CONFIRMATION_ENV_VAR}="
                f"{PROBE_CONFIRMATION_VALUE}"
            )
        if symbol not in _ALLOWED_SYMBOLS:
            raise ValueError(f"execution probe symbol must be one of {sorted(_ALLOWED_SYMBOLS)}")
        if not request_id.strip():
            raise ValueError("execution probe request_id must be non-empty")
        now = _utc(now_utc) if now_utc is not None else self._clock()
        self.gateway.preflight()

        active = self.state.active_trade()
        if active is not None:
            return self._advance(active, now)

        exposure = self.gateway.account_exposure()
        if exposure.positions or exposure.open_orders:
            raise AutonomousDemoStateError(
                "unowned Demo exposure/order found; refusing to start an execution probe"
            )

        daily = self.state.authorize_entry(
            now_utc=now,
            starting_capital_usd=SYNTHETIC_RISK_BUDGET_USD,
            config=self.config.risk_config,
        )
        mode = mode_override or (
            ProbeOrderType.TAKER if daily.entries % 4 < 2 else ProbeOrderType.MAKER
        )
        side = side_override or (
            IntentSide.BUY if daily.entries % 2 == 0 else IntentSide.SELL
        )

        quote = self._fetch_quote(symbol, now)
        mid_price = Decimal(str((quote.bid_price + quote.ask_price) / 2))
        market = self.public_market.instrument_snapshot(symbol=symbol)
        quantity = _size_probe_quantity(
            target=self.config.target_notional_quote_usd,
            maximum=self.config.maximum_notional_quote_usd,
            price=mid_price,
            market=market,
        )
        action = SetupAction.LONG if side is IntentSide.BUY else SetupAction.SHORT
        try:
            record = self.state.begin_trade(
                observation_id=f"execution-probe:{request_id}",
                candidate_id=f"{EXECUTION_PROBE_CANDIDATE_ID}:{mode.value}",
                symbol=symbol,
                action=action,
                target_quantity=quantity,
                reference_price=mid_price,
                now_utc=now,
            )
        except AutonomousDemoStateError as exc:
            return ProbeCycleResult(
                "REQUEST_ID_ALREADY_RESOLVED",
                None,
                f"request_id {request_id!r} already maps to a completed execution probe trade "
                f"with different parameters at the current market; use a new --request-id for a "
                f"new probe attempt ({exc})",
            )

        if record.phase is AutonomousTradePhase.OBSERVED:
            self.state.record_entry(
                now_utc=now,
                starting_capital_usd=SYNTHETIC_RISK_BUDGET_USD,
                config=self.config.risk_config,
            )
            self.journal.record_quote(
                probe_trade_id=record.trade_id, horizon_label="REFERENCE", quote=quote
            )
        return self._advance(record, now)

    def _advance(self, record: AutonomousTradeRecord, now: datetime) -> ProbeCycleResult:
        if record.phase is AutonomousTradePhase.SAFETY_HOLD:
            return ProbeCycleResult("SAFETY_HOLD", record, record.safety_reason or "manual review")
        if record.phase is AutonomousTradePhase.CLOSED:
            return ProbeCycleResult("CLOSED", record, f"realized_pnl_usd={record.realized_pnl_usd}")
        mode = _mode_from_candidate_id(record.candidate_id)
        if record.phase is AutonomousTradePhase.OBSERVED:
            self.gateway.set_leverage(symbol=record.symbol, leverage=PROBE_LEVERAGE)
            order = self._submit_entry(record, mode=mode, now=now)
            return self._await_and_resolve_entry(
                record, mode=mode, order=order, started_at=record.created_at_utc
            )
        if record.phase is AutonomousTradePhase.ENTRY_SUBMITTED:
            assert record.entry_client_order_id
            existing_order = self.orders.get(record.entry_client_order_id)
            assert existing_order is not None
            return self._await_and_resolve_entry(
                record, mode=mode, order=existing_order, started_at=record.created_at_utc
            )
        if record.phase is AutonomousTradePhase.OPEN:
            return self._flatten(record, now=now)
        assert record.phase is AutonomousTradePhase.EXIT_SUBMITTED
        return self._continue_exit(record)

    # -- entry -----------------------------------------------------------

    def _submit_entry(
        self, record: AutonomousTradeRecord, *, mode: ProbeOrderType, now: datetime
    ) -> PaperOrderRecord:
        key = f"execution-probe:{record.trade_id}:entry-v1"
        side = IntentSide.BUY if record.action is SetupAction.LONG else IntentSide.SELL
        order = self.orders.begin_order(
            idempotency_key=key,
            symbol=record.symbol,
            side=side,
            quantity=float(record.target_quantity),
            reference_price=float(record.reference_price),
            leg_group_id=record.trade_id,
            now_utc=now,
        )
        self.state.mark_entry_submitted(
            record.trade_id, client_order_id=order.client_order_id, now_utc=now
        )
        if order.state is PaperOrderState.PENDING_SUBMIT:
            order = self.orders.mark_submitted(order.client_order_id, now_utc=now)
            order_link_id = demo_order_link_id_for(order.client_order_id)
            if mode is ProbeOrderType.MAKER:
                quote = self._fetch_quote(record.symbol, now)
                price = Decimal(str(quote.bid_price if side is IntentSide.BUY else quote.ask_price))
                ack = self.gateway.place_post_only(
                    order_link_id=order_link_id,
                    symbol=record.symbol,
                    side=side,
                    quantity=record.target_quantity,
                    price=price,
                )
            else:
                ack = self.gateway.place_market(
                    order_link_id=order_link_id,
                    symbol=record.symbol,
                    side=side,
                    quantity=record.target_quantity,
                    reduce_only=False,
                )
            if ack.order_link_id != order_link_id:
                raise AutonomousDemoStateError("Bybit Demo order identity mismatch")
        return order

    def _await_and_resolve_entry(
        self,
        record: AutonomousTradeRecord,
        *,
        mode: ProbeOrderType,
        order: PaperOrderRecord,
        started_at: datetime,
    ) -> ProbeCycleResult:
        maker_deadline = started_at + timedelta(seconds=self.config.maker_fill_timeout_seconds)
        overall_deadline = started_at + timedelta(
            seconds=self.config.reconcile_timeout_seconds
            + (self.config.maker_fill_timeout_seconds if mode is ProbeOrderType.MAKER else 0)
        )
        cancel_attempted = False
        order_link_id = demo_order_link_id_for(order.client_order_id)
        while True:
            wall_now = self._clock()
            try:
                order, _, _ = self.reconciler.reconcile(order.client_order_id)
            except DemoExecutionLagError:
                if wall_now >= overall_deadline:
                    return ProbeCycleResult(
                        "PENDING_RECONCILIATION",
                        self.state.active_trade(),
                        "entry execution feed is lagging; rerun with the SAME --request-id",
                    )
                self._sleep(self.config.reconcile_poll_seconds)
                continue
            if order.state is PaperOrderState.FILLED:
                return self._finalize_filled_entry(record, order=order)
            if order.state is PaperOrderState.REJECTED:
                return self._close_zero_fill(
                    record, order=order, now=wall_now, detail="entry order rejected before any fill"
                )
            if order.state is PaperOrderState.CANCELED:
                if order.filled_quantity > 0:
                    return self._finalize_filled_entry(record, order=order)
                return self._close_zero_fill(
                    record,
                    order=order,
                    now=wall_now,
                    detail="maker entry canceled unfilled after the fill-probability timeout",
                )
            if mode is ProbeOrderType.MAKER and not cancel_attempted and wall_now >= maker_deadline:
                self.gateway.cancel(order_link_id=order_link_id, symbol=record.symbol)
                cancel_attempted = True
                continue
            if wall_now >= overall_deadline:
                if order.filled_quantity > 0:
                    return self._finalize_filled_entry(record, order=order)
                return ProbeCycleResult(
                    "PENDING_RECONCILIATION",
                    self.state.active_trade(),
                    "entry order still open past the probe deadline; rerun with the SAME "
                    "--request-id",
                )
            self._sleep(self.config.reconcile_poll_seconds)

    def _finalize_filled_entry(
        self, record: AutonomousTradeRecord, *, order: PaperOrderRecord
    ) -> ProbeCycleResult:
        assert order.average_fill_price is not None
        fills = self.orders.list_fills(order.client_order_id)
        filled_at = max((f.filled_at_utc for f in fills), default=order.updated_at_utc)
        opened = self.state.mark_open(
            record.trade_id,
            fill_price=Decimal(str(order.average_fill_price)),
            opened_at_utc=filled_at,
        )
        self._journal_entry(opened, order=order, resolved_at=filled_at)
        result = self._flatten(opened, now=self._clock())
        self._collect_markouts(opened.trade_id, opened.symbol, filled_at=filled_at)
        return result

    def _close_zero_fill(
        self, record: AutonomousTradeRecord, *, order: PaperOrderRecord, now: datetime, detail: str
    ) -> ProbeCycleResult:
        self._journal_entry(record, order=order, resolved_at=order.updated_at_utc)
        closed = self.state.mark_closed(
            record.trade_id, realized_pnl_usd=Decimal(0), closed_at_utc=now
        )
        return ProbeCycleResult("CLOSED_NO_FILL", closed, detail)

    # -- exit / flatten ----------------------------------------------------

    def _flatten(self, record: AutonomousTradeRecord, *, now: datetime) -> ProbeCycleResult:
        signed = self._signed_position(record.symbol)
        if signed == 0:
            held = self.state.mark_safety_hold(
                record.trade_id,
                reason="exchange/state position mismatch: OPEN phase but zero exchange exposure",
                now_utc=now,
            )
            return ProbeCycleResult("SAFETY_HOLD", held, held.safety_reason or "")
        attempt = self._next_exit_attempt(record)
        if attempt > self.config.maximum_exit_attempts:
            held = self.state.mark_safety_hold(
                record.trade_id, reason="maximum residual exit attempts reached", now_utc=now
            )
            return ProbeCycleResult("SAFETY_HOLD", held, held.safety_reason or "")
        side = IntentSide.SELL if signed > 0 else IntentSide.BUY
        quantity = abs(signed)
        key = f"execution-probe:{record.trade_id}:exit-v{attempt}"
        market = self.public_market.instrument_snapshot(symbol=record.symbol)
        order = self.orders.begin_order(
            idempotency_key=key,
            symbol=record.symbol,
            side=side,
            quantity=float(quantity),
            reference_price=float(market.last_price),
            leg_group_id=record.trade_id,
            now_utc=now,
        )
        self.state.mark_exit_submitted(
            record.trade_id,
            client_order_id=order.client_order_id,
            reason="EXECUTION_PROBE_IMMEDIATE_FLATTEN",
            now_utc=now,
        )
        if order.state is PaperOrderState.PENDING_SUBMIT:
            order = self.orders.mark_submitted(order.client_order_id, now_utc=now)
            order_link_id = demo_order_link_id_for(order.client_order_id)
            ack = self.gateway.place_market(
                order_link_id=order_link_id,
                symbol=record.symbol,
                side=side,
                quantity=quantity,
                reduce_only=True,
            )
            if ack.order_link_id != order_link_id:
                raise AutonomousDemoStateError("Bybit Demo order identity mismatch")
        current = self.state.active_trade()
        return self._continue_exit(current or record)

    def _continue_exit(self, record: AutonomousTradeRecord) -> ProbeCycleResult:
        assert record.exit_client_order_id
        deadline = self._clock() + timedelta(seconds=self.config.reconcile_timeout_seconds)
        while True:
            wall_now = self._clock()
            try:
                order, _, _ = self.reconciler.reconcile(record.exit_client_order_id)
            except DemoExecutionLagError:
                if wall_now >= deadline:
                    return ProbeCycleResult(
                        "PENDING_RECONCILIATION",
                        record,
                        "exit execution feed is lagging; rerun with the SAME --request-id",
                    )
                self._sleep(self.config.reconcile_poll_seconds)
                continue
            signed = self._signed_position(record.symbol)
            if signed == 0 and order.filled_quantity > 0:
                return self._close(record, now=wall_now)
            if order.state in {PaperOrderState.CANCELED, PaperOrderState.REJECTED}:
                if signed == 0:
                    return self._close(record, now=wall_now)
                return self._flatten(record, now=wall_now)
            if wall_now >= deadline:
                return ProbeCycleResult(
                    "PENDING_RECONCILIATION",
                    record,
                    "reduce-only exit awaiting reconciliation; rerun with the SAME --request-id",
                )
            self._sleep(self.config.reconcile_poll_seconds)

    def _close(self, record: AutonomousTradeRecord, *, now: datetime) -> ProbeCycleResult:
        assert record.entry_client_order_id and record.exit_client_order_id
        entry = self.orders.get(record.entry_client_order_id)
        exit_orders = tuple(
            order
            for order in self.orders.list_by_leg_group(record.trade_id)
            if order.client_order_id != record.entry_client_order_id
        )
        assert entry is not None and exit_orders
        exited_quantity = sum(
            (Decimal(str(order.filled_quantity)) for order in exit_orders), start=Decimal(0)
        )
        if abs(exited_quantity - Decimal(str(entry.filled_quantity))) > Decimal("0.000000001"):
            held = self.state.mark_safety_hold(
                record.trade_id,
                reason="flat exchange position does not match durable exit executions",
                now_utc=now,
            )
            return ProbeCycleResult("SAFETY_HOLD", held, held.safety_reason or "")
        direction = Decimal(1) if record.action is SetupAction.LONG else Decimal(-1)
        assert entry.average_fill_price is not None
        entry_notional = Decimal(str(entry.average_fill_price * entry.filled_quantity))
        exit_notional = sum(
            (
                Decimal(str((order.average_fill_price or 0) * order.filled_quantity))
                for order in exit_orders
            ),
            start=Decimal(0),
        )
        gross = direction * (exit_notional - entry_notional)
        costs = Decimal(
            str(
                entry.fee_cost_quote
                + entry.slippage_cost_quote
                + sum(order.fee_cost_quote + order.slippage_cost_quote for order in exit_orders)
            )
        )
        pnl = gross - costs
        closed = self.state.mark_closed(record.trade_id, realized_pnl_usd=pnl, closed_at_utc=now)
        self.state.record_close(
            now_utc=now,
            starting_capital_usd=SYNTHETIC_RISK_BUDGET_USD,
            realized_pnl_usd=pnl,
            config=self.config.risk_config,
        )
        return ProbeCycleResult("CLOSED", closed, f"realized_pnl_usd={pnl}")

    # -- evidence ----------------------------------------------------------

    def _journal_entry(
        self, record: AutonomousTradeRecord, *, order: PaperOrderRecord, resolved_at: datetime
    ) -> None:
        rejected = order.state in {PaperOrderState.REJECTED, PaperOrderState.CANCELED} and (
            order.filled_quantity == 0
        )
        observation = PaperOrderObservation(
            order_id=order.client_order_id,
            symbol=record.symbol,
            venue=PROBE_VENUE,
            side=order.side,
            requested_quantity=order.quantity,
            decision_timestamp_utc=record.created_at_utc,
            submitted_at_utc=order.created_at_utc,
            resolved_at_utc=resolved_at,
            filled_price=order.average_fill_price or 0.0,
            filled_quantity=order.filled_quantity,
            rejected=rejected,
            fee_cost_quote=order.fee_cost_quote,
            funding_cost_quote=order.funding_cost_quote,
        )
        self.journal.record_order_observation(
            probe_trade_id=record.trade_id,
            probe_mode=_mode_from_candidate_id(record.candidate_id).value,
            request_id=record.observation_id.removeprefix("execution-probe:"),
            observation=observation,
            now_utc=self._clock(),
        )

    def _collect_markouts(self, trade_id: str, symbol: str, *, filled_at: datetime) -> None:
        """Best-effort: the exchange position is already flat by the time this
        runs, so a failed public-data poll skips that one horizon rather than
        failing the (already-safe) probe cycle."""
        for horizon in self.config.markout_horizons_seconds:
            target = filled_at + timedelta(seconds=horizon)
            wait = (target - self._clock()).total_seconds()
            if wait > 0:
                self._sleep(wait)
            try:
                quote = self._fetch_quote(symbol, self._clock())
            except (KeyError, ValueError, RuntimeError):
                continue
            self.journal.record_quote(
                probe_trade_id=trade_id, horizon_label=f"T+{horizon}s", quote=quote
            )

    def _fetch_quote(self, symbol: str, now: datetime) -> TopOfBookQuote:
        raw = self.ticker.get_ticker(symbol, category="linear")
        self._seq += 1
        return TopOfBookQuote(
            symbol=symbol,
            venue=PROBE_VENUE,
            timestamp_utc=now,
            source_sequence=self._seq,
            bid_price=float(raw["bid1Price"]),
            ask_price=float(raw["ask1Price"]),
            bid_quantity=float(raw["bid1Size"]),
            ask_quantity=float(raw["ask1Size"]),
        )

    def _signed_position(self, symbol: str) -> Decimal:
        return sum(
            (
                p.size if p.side == "Buy" else -p.size if p.side == "Sell" else Decimal(0)
                for p in self.gateway.fetch_positions(symbol=symbol)
            ),
            start=Decimal("0"),
        )

    def _next_exit_attempt(self, record: AutonomousTradeRecord) -> int:
        return 1 + sum(
            order.idempotency_key.startswith(f"execution-probe:{record.trade_id}:exit-v")
            for order in self.orders.list_by_leg_group(record.trade_id)
        )


def _mode_from_candidate_id(candidate_id: str) -> ProbeOrderType:
    prefix = f"{EXECUTION_PROBE_CANDIDATE_ID}:"
    if not candidate_id.startswith(prefix):
        raise AutonomousDemoStateError(
            f"unexpected non-probe candidate_id in the execution probe state store: "
            f"{candidate_id!r}"
        )
    return ProbeOrderType(candidate_id.removeprefix(prefix))


def _size_probe_quantity(
    *, target: Decimal, maximum: Decimal, price: Decimal, market: PublicLinearInstrumentSnapshot
) -> Decimal:
    raw_quantity = target / price
    quantity = (
        raw_quantity / market.quantity_step
    ).to_integral_value(rounding=ROUND_DOWN) * market.quantity_step
    if quantity < market.minimum_order_quantity:
        quantity = market.minimum_order_quantity
    actual_notional = quantity * price
    if actual_notional > maximum:
        raise ValueError(
            f"{market.symbol}'s minimum tradable notional (~{actual_notional} USDT) exceeds the "
            f"execution probe's maximum notional cap ({maximum} USDT); exclude this symbol or "
            "raise the cap, bounded by HARD_MAXIMUM_NOTIONAL_QUOTE_USD"
        )
    return quantity


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        raise ValueError("execution probe timestamp must be timezone-aware")
    return value.astimezone(UTC)
