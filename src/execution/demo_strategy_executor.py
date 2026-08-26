"""Crash-safe Bybit Demo execution skeleton for a future qualified strategy.

No signal generator or continuously runnable service imports this module after
the retired v1/v2 experiments were removed.  It retains tested order lifecycle,
partial-fill recovery, reduce-only exits, sizing and durable risk controls.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pandas as pd

from src.engines.contracts import SetupAction
from src.execution.bybit_demo_gateway import (
    BYBIT_DEMO_REST_URL,
    BybitDemoGateway,
    BybitPublicLinearMarketData,
)
from src.execution.demo_autonomous_risk import (
    AtrExitConfig,
    AutonomousDemoRiskConfig,
    DemoExitReason,
    atr_stop_take_profit_bps,
    autonomous_demo_exit_reason,
    size_autonomous_demo_trade,
)
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
from src.execution.intent import IntentSide
from src.execution.paper_reconciliation import PaperOrderRecord, PaperOrderState, PaperOrderStore

STRATEGY_CONFIRMATION_ENV_VAR = "GREENFIELD_DEMO_STRATEGY_CONFIRMATION"
STRATEGY_CONFIRMATION_VALUE = "CONTINUOUS_BYBIT_DEMO_STRATEGY_ONLY"


@dataclass(frozen=True, slots=True)
class DemoStrategyCycleResult:
    status: str
    trade: AutonomousTradeRecord | None
    detail: str


class DemoStrategyExecutor:
    def __init__(
        self,
        *,
        gateway: BybitDemoGateway,
        public_market: BybitPublicLinearMarketData,
        orders: PaperOrderStore,
        state: AutonomousDemoStateStore,
        config: AutonomousDemoRiskConfig,
        atr_exit_config: AtrExitConfig | None = None,
        use_post_only_entry: bool = False,
    ) -> None:
        if gateway.endpoint != BYBIT_DEMO_REST_URL:
            raise ValueError("strategy execution must be pinned to Bybit Demo")
        self.gateway = gateway
        self.public_market = public_market
        self.orders = orders
        self.state = state
        self.config = config
        # Entry type and volatility-scaled exits are explicit adapter choices;
        # the neutral skeleton has no hidden strategy defaults.
        self.atr_exit_config = atr_exit_config
        self.use_post_only_entry = use_post_only_entry
        self.reconciler = DemoOrderReconciler(gateway=gateway, store=orders)
        self._preflight_verified_at: datetime | None = None

    def advance(
        self,
        *,
        env: Mapping[str, str],
        symbol: str,
        action: SetupAction,
        observation_id: str,
        candidate_id: str,
        now_utc: datetime | None = None,
        candles: pd.DataFrame | None = None,
    ) -> DemoStrategyCycleResult:
        require_demo_paper_environment(env, order_submission=True)
        if env.get(STRATEGY_CONFIRMATION_ENV_VAR) != STRATEGY_CONFIRMATION_VALUE:
            raise ValueError(
                "Demo strategy execution requires "
                f"{STRATEGY_CONFIRMATION_ENV_VAR}={STRATEGY_CONFIRMATION_VALUE}"
            )
        now = (now_utc or datetime.now(UTC)).astimezone(UTC)
        if (
            self._preflight_verified_at is None
            or now < self._preflight_verified_at
            or now - self._preflight_verified_at >= timedelta(minutes=15)
        ):
            self.gateway.preflight()
            self._preflight_verified_at = now
        active = self.state.active_trade()
        if active is not None:
            return self._advance_active(active, now)
        exposure = self.gateway.account_exposure()
        if exposure.positions or exposure.open_orders:
            raise AutonomousDemoStateError("unowned Demo exposure/order found; refusing to trade")
        if action not in {SetupAction.LONG, SetupAction.SHORT}:
            return DemoStrategyCycleResult("WAIT", None, "strategy adapter returned WAIT")
        balance = self.gateway.account_balance()
        capital = min(balance.total_equity_usd, balance.total_available_balance_usd)
        # Reuse the day's frozen baseline for risk-ledger writes; sizing below
        # still uses live capital so ordinary PnL/fee drift changes position
        # size without rewriting the daily-loss reference point.
        daily = self.state.daily_risk_state(now)
        daily_capital = daily.starting_capital_usd if daily is not None else capital
        self.state.authorize_entry(
            now_utc=now, starting_capital_usd=daily_capital, config=self.config
        )
        market = self.public_market.instrument_snapshot(symbol=symbol)
        sizing = size_autonomous_demo_trade(balance, market, self.config)
        stop_loss_bps: Decimal | None = None
        take_profit_bps: Decimal | None = None
        if self.atr_exit_config is not None:
            if candles is None:
                raise ValueError("ATR-scaled exits require candles to be supplied")
            stop_loss_bps, take_profit_bps = atr_stop_take_profit_bps(
                candles, config=self.atr_exit_config
            )
        trade = self.state.begin_trade(
            observation_id=observation_id,
            candidate_id=candidate_id,
            symbol=symbol,
            action=action,
            target_quantity=sizing.quantity,
            reference_price=market.last_price,
            now_utc=now,
            stop_loss_bps=stop_loss_bps,
            take_profit_bps=take_profit_bps,
        )
        self.gateway.set_leverage(symbol=symbol, leverage=self.config.leverage)
        order = self._submit(
            trade,
            exit_reason=None,
            quantity=sizing.quantity,
            reference_price=market.last_price,
            now=now,
        )
        self.state.record_entry(now_utc=now, starting_capital_usd=daily_capital, config=self.config)
        try:
            order, _, _ = self.reconciler.reconcile(order.client_order_id)
        except DemoExecutionLagError:
            return DemoStrategyCycleResult(
                "ENTRY_SUBMITTED",
                self.state.active_trade(),
                "entry execution feed is lagging; reconciliation will retry",
            )
        if order.state is PaperOrderState.FILLED and order.average_fill_price is not None:
            trade = self.state.mark_open(
                trade.trade_id, fill_price=Decimal(str(order.average_fill_price)), opened_at_utc=now
            )
            return DemoStrategyCycleResult("OPEN", trade, "Demo entry filled")
        rejected = self._close_rejected_entry(trade, now, order)
        if rejected is not None:
            return rejected
        return DemoStrategyCycleResult(
            "ENTRY_SUBMITTED", self.state.active_trade(), "entry awaiting reconciliation"
        )

    def _advance_active(
        self, trade: AutonomousTradeRecord, now: datetime
    ) -> DemoStrategyCycleResult:
        if trade.phase is AutonomousTradePhase.SAFETY_HOLD:
            return DemoStrategyCycleResult(
                "SAFETY_HOLD", trade, trade.safety_reason or "manual review"
            )
        if trade.phase is AutonomousTradePhase.ENTRY_SUBMITTED:
            assert trade.entry_client_order_id
            try:
                order, _, _ = self.reconciler.reconcile(trade.entry_client_order_id)
            except DemoExecutionLagError:
                return DemoStrategyCycleResult(
                    "ENTRY_SUBMITTED",
                    trade,
                    "entry execution feed is lagging; reconciliation will retry",
                )
            if order.state is PaperOrderState.FILLED and order.average_fill_price is not None:
                trade = self.state.mark_open(
                    trade.trade_id,
                    fill_price=Decimal(str(order.average_fill_price)),
                    opened_at_utc=now,
                )
            else:
                rejected = self._close_rejected_entry(trade, now, order)
                if rejected is not None:
                    return rejected
                return DemoStrategyCycleResult(
                    "ENTRY_SUBMITTED", trade, "entry awaiting reconciliation"
                )
        positions = self.gateway.fetch_positions(symbol=trade.symbol)
        signed = sum(
            (p.size if p.side == "Buy" else -p.size if p.side == "Sell" else Decimal(0))
            for p in positions
        )
        if trade.phase is AutonomousTradePhase.EXIT_SUBMITTED:
            assert trade.exit_client_order_id
            try:
                order, _, _ = self.reconciler.reconcile(trade.exit_client_order_id)
            except DemoExecutionLagError:
                return DemoStrategyCycleResult(
                    "EXIT_SUBMITTED",
                    trade,
                    "exit execution feed is lagging; reconciliation will retry",
                )
            signed = self._signed_position(trade.symbol)
            if signed == 0 and order.filled_quantity > 0:
                return self._close(trade, now)
            if order.state in {PaperOrderState.CANCELED, PaperOrderState.REJECTED}:
                if signed == 0:
                    return self._close(trade, now)
                if self._next_exit_attempt(trade) > 5:
                    held = self.state.mark_safety_hold(
                        trade.trade_id,
                        reason="maximum residual exit attempts reached",
                        now_utc=now,
                    )
                    return DemoStrategyCycleResult("SAFETY_HOLD", held, held.safety_reason or "")
                market = self.public_market.instrument_snapshot(symbol=trade.symbol)
                residual_reason = DemoExitReason(trade.exit_reason or "")
                replacement = self._submit(
                    trade,
                    exit_reason=residual_reason,
                    quantity=abs(signed),
                    reference_price=market.last_price,
                    now=now,
                )
                try:
                    replacement, _, _ = self.reconciler.reconcile(
                        replacement.client_order_id
                    )
                except DemoExecutionLagError:
                    pass
                if self._signed_position(trade.symbol) == 0:
                    return self._close(self.state.active_trade() or trade, now)
                return DemoStrategyCycleResult(
                    "EXIT_SUBMITTED",
                    self.state.active_trade(),
                    "residual reduce-only exit submitted",
                )
            return DemoStrategyCycleResult(
                "EXIT_SUBMITTED", trade, "reduce-only exit awaiting reconciliation"
            )
        if signed == 0 or trade.entry_fill_price is None or trade.opened_at_utc is None:
            held = self.state.mark_safety_hold(
                trade.trade_id, reason="exchange/state position mismatch", now_utc=now
            )
            return DemoStrategyCycleResult("SAFETY_HOLD", held, held.safety_reason or "mismatch")
        market = self.public_market.instrument_snapshot(symbol=trade.symbol)
        reason = autonomous_demo_exit_reason(
            action=trade.action,
            entry_price=trade.entry_fill_price,
            current_price=market.last_price,
            opened_at_utc=trade.opened_at_utc,
            now_utc=now,
            config=self.config,
            stop_loss_bps=trade.stop_loss_bps,
            take_profit_bps=trade.take_profit_bps,
        )
        if reason is None:
            return DemoStrategyCycleResult("OPEN", trade, "stop/target/time exit not reached")
        order = self._submit(
            trade,
            exit_reason=reason,
            quantity=abs(signed),
            reference_price=market.last_price,
            now=now,
        )
        try:
            order, _, _ = self.reconciler.reconcile(order.client_order_id)
        except DemoExecutionLagError:
            return DemoStrategyCycleResult(
                "EXIT_SUBMITTED",
                self.state.active_trade(),
                "exit execution feed is lagging; reconciliation will retry",
            )
        if self._signed_position(trade.symbol) == 0 and order.state is PaperOrderState.FILLED:
            return self._close(self.state.active_trade() or trade, now)
        return DemoStrategyCycleResult(
            "EXIT_SUBMITTED", self.state.active_trade(), "reduce-only exit submitted"
        )

    def _submit(
        self,
        trade: AutonomousTradeRecord,
        *,
        exit_reason: DemoExitReason | None,
        quantity: Decimal,
        reference_price: Decimal,
        now: datetime,
    ) -> PaperOrderRecord:
        suffix = "entry-v1" if exit_reason is None else f"exit-v{self._next_exit_attempt(trade)}"
        key = f"demo-strategy:{trade.trade_id}:{suffix}"
        side = IntentSide.BUY if trade.action is SetupAction.LONG else IntentSide.SELL
        if exit_reason is not None:
            side = IntentSide.SELL if side is IntentSide.BUY else IntentSide.BUY
        order = self.orders.begin_order(
            idempotency_key=key,
            symbol=trade.symbol,
            side=side,
            quantity=float(quantity),
            reference_price=float(reference_price),
            leg_group_id=trade.trade_id,
            now_utc=now,
        )
        if exit_reason is None:
            self.state.mark_entry_submitted(
                trade.trade_id, client_order_id=order.client_order_id, now_utc=now
            )
        else:
            self.state.mark_exit_submitted(
                trade.trade_id,
                client_order_id=order.client_order_id,
                reason=exit_reason.value,
                now_utc=now,
            )
        if order.state is PaperOrderState.PENDING_SUBMIT:
            order = self.orders.mark_submitted(order.client_order_id, now_utc=now)
            order_link_id = demo_order_link_id_for(order.client_order_id)
            # A future adapter may select post-only entry to reduce taker fee
            # and slippage, at the cost of sometimes not filling at
            # all if the market moves before it would cross - handled by
            # _close_rejected_entry. Exits always stay market: a reduce-only
            # exit's job is certainty of flattening the position, not cost.
            if exit_reason is None and self.use_post_only_entry:
                ack = self.gateway.place_post_only(
                    order_link_id=order_link_id,
                    symbol=trade.symbol,
                    side=side,
                    quantity=quantity,
                    price=reference_price,
                )
            else:
                ack = self.gateway.place_market(
                    order_link_id=order_link_id,
                    symbol=trade.symbol,
                    side=side,
                    quantity=quantity,
                    reduce_only=exit_reason is not None,
                )
            if ack.order_link_id != order_link_id:
                raise AutonomousDemoStateError("Bybit Demo order identity mismatch")
        return order

    def _close_rejected_entry(
        self, trade: AutonomousTradeRecord, now: datetime, order: PaperOrderRecord
    ) -> DemoStrategyCycleResult | None:
        """Close a trade whose entry order was cleanly rejected with zero fill.

        Only relevant once a future adapter opts into `use_post_only_entry`:
        a post-only order that would have crossed
        the spread is rejected outright rather than partially filling, so
        there is never any exposure to reconcile. Without this, the trade
        would sit in ENTRY_SUBMITTED forever and (maximum_open_positions=1)
        block every later entry.
        """
        if order.state is not PaperOrderState.REJECTED or order.filled_quantity != 0:
            return None
        closed = self.state.mark_closed(
            trade.trade_id, realized_pnl_usd=Decimal(0), closed_at_utc=now
        )
        return DemoStrategyCycleResult(
            "CLOSED", closed, "entry order rejected before any fill (post-only did not cross)"
        )

    def _next_exit_attempt(self, trade: AutonomousTradeRecord) -> int:
        return 1 + sum(
            order.idempotency_key.startswith(f"demo-strategy:{trade.trade_id}:exit-v")
            for order in self.orders.list_by_leg_group(trade.trade_id)
        )

    def _signed_position(self, symbol: str) -> Decimal:
        return sum(
            (
                p.size if p.side == "Buy" else -p.size if p.side == "Sell" else Decimal(0)
                for p in self.gateway.fetch_positions(symbol=symbol)
            ),
            start=Decimal("0"),
        )

    def _close(self, trade: AutonomousTradeRecord, now: datetime) -> DemoStrategyCycleResult:
        assert trade.entry_client_order_id and trade.exit_client_order_id
        entry = self.orders.get(trade.entry_client_order_id)
        exit_orders = tuple(
            order
            for order in self.orders.list_by_leg_group(trade.trade_id)
            if order.client_order_id != trade.entry_client_order_id
        )
        assert entry and exit_orders
        exited_quantity = sum(
            (Decimal(str(order.filled_quantity)) for order in exit_orders),
            start=Decimal(0),
        )
        if abs(exited_quantity - Decimal(str(entry.filled_quantity))) > Decimal("0.000000001"):
            held = self.state.mark_safety_hold(
                trade.trade_id,
                reason="flat exchange position does not match durable exit executions",
                now_utc=now,
            )
            return DemoStrategyCycleResult("SAFETY_HOLD", held, held.safety_reason or "")
        direction = Decimal(1) if trade.action is SetupAction.LONG else Decimal(-1)
        if entry.average_fill_price is None or any(
            order.average_fill_price is None for order in exit_orders if order.filled_quantity > 0
        ):
            raise AutonomousDemoStateError("filled Demo strategy orders require average prices")
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
                + sum(
                    order.fee_cost_quote + order.slippage_cost_quote
                    for order in exit_orders
                )
            )
        )
        pnl = gross - costs
        closed = self.state.mark_closed(trade.trade_id, realized_pnl_usd=pnl, closed_at_utc=now)
        balance = self.gateway.account_balance()
        capital = min(balance.total_equity_usd, balance.total_available_balance_usd)
        self.state.record_close(
            now_utc=now, starting_capital_usd=capital, realized_pnl_usd=pnl, config=self.config
        )
        return DemoStrategyCycleResult("CLOSED", closed, f"realized_pnl_usd={pnl}")
