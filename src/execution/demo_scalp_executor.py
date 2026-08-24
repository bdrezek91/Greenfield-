"""Crash-safe ATAS/MC experimental scalper restricted to Bybit Demo."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal

from src.engines.contracts import SetupAction
from src.execution.bybit_demo_gateway import (
    BYBIT_DEMO_REST_URL,
    BybitDemoGateway,
    BybitPublicLinearMarketData,
)
from src.execution.demo_autonomous_risk import (
    AutonomousDemoRiskConfig,
    DemoExitReason,
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
from src.execution.demo_order_reconciler import DemoOrderReconciler, demo_order_link_id_for
from src.execution.intent import IntentSide
from src.execution.paper_reconciliation import PaperOrderRecord, PaperOrderState, PaperOrderStore

SCALP_CONFIRMATION_ENV_VAR = "GREENFIELD_DEMO_SCALP_CONFIRMATION"
SCALP_CONFIRMATION_VALUE = "CONTINUOUS_BYBIT_DEMO_SCALP_ONLY"


def scalp_risk_config() -> AutonomousDemoRiskConfig:
    return AutonomousDemoRiskConfig(
        maximum_trades_per_utc_day=12,
        maximum_holding_seconds=600,
        cooldown_seconds=300,
    )


@dataclass(frozen=True, slots=True)
class DemoScalpCycleResult:
    status: str
    trade: AutonomousTradeRecord | None
    detail: str


class DemoScalpExecutor:
    def __init__(
        self,
        *,
        gateway: BybitDemoGateway,
        public_market: BybitPublicLinearMarketData,
        orders: PaperOrderStore,
        state: AutonomousDemoStateStore,
        config: AutonomousDemoRiskConfig | None = None,
    ) -> None:
        if gateway.endpoint != BYBIT_DEMO_REST_URL:
            raise ValueError("scalper execution must be pinned to Bybit Demo")
        self.gateway = gateway
        self.public_market = public_market
        self.orders = orders
        self.state = state
        self.config = config or scalp_risk_config()
        self.reconciler = DemoOrderReconciler(gateway=gateway, store=orders)

    def advance(
        self,
        *,
        env: Mapping[str, str],
        symbol: str,
        action: SetupAction,
        observation_id: str,
        candidate_id: str,
        now_utc: datetime | None = None,
    ) -> DemoScalpCycleResult:
        require_demo_paper_environment(env, order_submission=True)
        if env.get(SCALP_CONFIRMATION_ENV_VAR) != SCALP_CONFIRMATION_VALUE:
            raise ValueError(
                f"Demo scalper requires {SCALP_CONFIRMATION_ENV_VAR}={SCALP_CONFIRMATION_VALUE}"
            )
        now = (now_utc or datetime.now(UTC)).astimezone(UTC)
        self.gateway.preflight()
        active = self.state.active_trade()
        if active is not None:
            return self._advance_active(active, now)
        exposure = self.gateway.account_exposure()
        if exposure.positions or exposure.open_orders:
            raise AutonomousDemoStateError("unowned Demo exposure/order found; refusing to trade")
        if action not in {SetupAction.LONG, SetupAction.SHORT}:
            return DemoScalpCycleResult("WAIT", None, "ATAS families and MC veto are not aligned")
        balance = self.gateway.account_balance()
        capital = min(balance.total_equity_usd, balance.total_available_balance_usd)
        self.state.authorize_entry(now_utc=now, starting_capital_usd=capital, config=self.config)
        market = self.public_market.instrument_snapshot(symbol=symbol)
        sizing = size_autonomous_demo_trade(balance, market, self.config)
        trade = self.state.begin_trade(
            observation_id=observation_id,
            candidate_id=candidate_id,
            symbol=symbol,
            action=action,
            target_quantity=sizing.quantity,
            reference_price=market.last_price,
            now_utc=now,
        )
        self.gateway.set_leverage(symbol=symbol, leverage=self.config.leverage)
        order = self._submit(
            trade,
            exit_reason=None,
            quantity=sizing.quantity,
            reference_price=market.last_price,
            now=now,
        )
        self.state.record_entry(now_utc=now, starting_capital_usd=capital, config=self.config)
        order, _, _ = self.reconciler.reconcile(order.client_order_id)
        if order.state is PaperOrderState.FILLED and order.average_fill_price is not None:
            trade = self.state.mark_open(
                trade.trade_id, fill_price=Decimal(str(order.average_fill_price)), opened_at_utc=now
            )
            return DemoScalpCycleResult("OPEN", trade, "Demo entry filled")
        return DemoScalpCycleResult(
            "ENTRY_SUBMITTED", self.state.active_trade(), "entry awaiting reconciliation"
        )

    def _advance_active(self, trade: AutonomousTradeRecord, now: datetime) -> DemoScalpCycleResult:
        if trade.phase is AutonomousTradePhase.SAFETY_HOLD:
            return DemoScalpCycleResult(
                "SAFETY_HOLD", trade, trade.safety_reason or "manual review"
            )
        if trade.phase is AutonomousTradePhase.ENTRY_SUBMITTED:
            assert trade.entry_client_order_id
            order, _, _ = self.reconciler.reconcile(trade.entry_client_order_id)
            if order.state is PaperOrderState.FILLED and order.average_fill_price is not None:
                trade = self.state.mark_open(
                    trade.trade_id,
                    fill_price=Decimal(str(order.average_fill_price)),
                    opened_at_utc=now,
                )
            else:
                return DemoScalpCycleResult(
                    "ENTRY_SUBMITTED", trade, "entry awaiting reconciliation"
                )
        positions = self.gateway.fetch_positions(symbol=trade.symbol)
        signed = sum(
            (p.size if p.side == "Buy" else -p.size if p.side == "Sell" else Decimal(0))
            for p in positions
        )
        if trade.phase is AutonomousTradePhase.EXIT_SUBMITTED:
            assert trade.exit_client_order_id
            order, _, _ = self.reconciler.reconcile(trade.exit_client_order_id)
            if signed == 0 and order.state is PaperOrderState.FILLED:
                return self._close(trade, now)
            return DemoScalpCycleResult(
                "EXIT_SUBMITTED", trade, "reduce-only exit awaiting reconciliation"
            )
        if signed == 0 or trade.entry_fill_price is None or trade.opened_at_utc is None:
            held = self.state.mark_safety_hold(
                trade.trade_id, reason="exchange/state position mismatch", now_utc=now
            )
            return DemoScalpCycleResult("SAFETY_HOLD", held, held.safety_reason or "mismatch")
        market = self.public_market.instrument_snapshot(symbol=trade.symbol)
        reason = autonomous_demo_exit_reason(
            action=trade.action,
            entry_price=trade.entry_fill_price,
            current_price=market.last_price,
            opened_at_utc=trade.opened_at_utc,
            now_utc=now,
            config=self.config,
        )
        if reason is None:
            return DemoScalpCycleResult("OPEN", trade, "stop/target/time exit not reached")
        order = self._submit(
            trade,
            exit_reason=reason,
            quantity=abs(signed),
            reference_price=market.last_price,
            now=now,
        )
        order, _, _ = self.reconciler.reconcile(order.client_order_id)
        if self._signed_position(trade.symbol) == 0 and order.state is PaperOrderState.FILLED:
            return self._close(self.state.active_trade() or trade, now)
        return DemoScalpCycleResult(
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
        suffix = "entry-v1" if exit_reason is None else "exit-v1"
        key = f"demo-scalp:{trade.trade_id}:{suffix}"
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
            ack = self.gateway.place_market(
                order_link_id=demo_order_link_id_for(order.client_order_id),
                symbol=trade.symbol,
                side=side,
                quantity=quantity,
                reduce_only=exit_reason is not None,
            )
            if ack.order_link_id != demo_order_link_id_for(order.client_order_id):
                raise AutonomousDemoStateError("Bybit Demo order identity mismatch")
        return order

    def _signed_position(self, symbol: str) -> Decimal:
        return sum(
            (
                p.size if p.side == "Buy" else -p.size if p.side == "Sell" else Decimal(0)
                for p in self.gateway.fetch_positions(symbol=symbol)
            ),
            start=Decimal("0"),
        )

    def _close(self, trade: AutonomousTradeRecord, now: datetime) -> DemoScalpCycleResult:
        assert trade.entry_client_order_id and trade.exit_client_order_id
        entry = self.orders.get(trade.entry_client_order_id)
        exit_order = self.orders.get(trade.exit_client_order_id)
        assert entry and exit_order
        direction = Decimal(1) if trade.action is SetupAction.LONG else Decimal(-1)
        if entry.average_fill_price is None or exit_order.average_fill_price is None:
            raise AutonomousDemoStateError("filled Demo scalp orders require average prices")
        entry_notional = Decimal(str(entry.average_fill_price * entry.filled_quantity))
        exit_notional = Decimal(str(exit_order.average_fill_price * exit_order.filled_quantity))
        gross = direction * (exit_notional - entry_notional)
        costs = Decimal(
            str(
                entry.fee_cost_quote
                + exit_order.fee_cost_quote
                + entry.slippage_cost_quote
                + exit_order.slippage_cost_quote
            )
        )
        pnl = gross - costs
        closed = self.state.mark_closed(trade.trade_id, realized_pnl_usd=pnl, closed_at_utc=now)
        balance = self.gateway.account_balance()
        capital = min(balance.total_equity_usd, balance.total_available_balance_usd)
        self.state.record_close(
            now_utc=now, starting_capital_usd=capital, realized_pnl_usd=pnl, config=self.config
        )
        return DemoScalpCycleResult("CLOSED", closed, f"realized_pnl_usd={pnl}")
