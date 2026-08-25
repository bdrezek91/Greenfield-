from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

from src.engines.contracts import SetupAction
from src.execution.bybit_demo_gateway import (
    BYBIT_DEMO_REST_URL,
    BYBIT_PUBLIC_REST_URL,
    DemoAccountBalance,
    DemoAccountExposure,
    DemoExecution,
    DemoOrderAck,
    DemoOrderSnapshot,
    DemoOrderStatus,
    DemoPositionSnapshot,
    DemoPreflightReport,
    PublicLinearInstrumentSnapshot,
)
from src.execution.demo_autonomous_state import AutonomousDemoStateStore
from src.execution.demo_operator import (
    DEMO_ORDER_CONFIRMATION_ENV_VAR,
    DEMO_ORDER_CONFIRMATION_VALUE,
)
from src.execution.demo_scalp_executor import (
    SCALP_CONFIRMATION_ENV_VAR,
    SCALP_CONFIRMATION_VALUE,
    DemoScalpExecutor,
)
from src.execution.intent import IntentSide
from src.execution.paper_reconciliation import PaperOrderStore

NOW = datetime(2026, 8, 24, 20, tzinfo=UTC)


class Market:
    endpoint = BYBIT_PUBLIC_REST_URL

    def __init__(self) -> None:
        self.price = Decimal("100000")

    def instrument_snapshot(self, *, symbol: str) -> PublicLinearInstrumentSnapshot:
        return PublicLinearInstrumentSnapshot(
            symbol, self.price, Decimal("0.001"), Decimal("0.001")
        )


class Gateway:
    endpoint = BYBIT_DEMO_REST_URL

    def __init__(self, market: Market) -> None:
        self.market = market
        self.position = Decimal("0")
        self.calls: list[tuple[IntentSide, Decimal, bool]] = []
        self.orders: dict[str, DemoOrderSnapshot] = {}
        self.executions: dict[str, tuple[DemoExecution, ...]] = {}
        self.balance = Decimal("100")
        self.preflight_calls = 0

    def preflight(self) -> DemoPreflightReport:
        self.preflight_calls += 1
        return DemoPreflightReport(
            self.endpoint, True, True, True, ("127.0.0.1",), ("Derivatives",), 1, 0, 0
        )

    def account_balance(self) -> DemoAccountBalance:
        return DemoAccountBalance(self.balance, self.balance, self.balance)

    def account_exposure(self) -> DemoAccountExposure:
        positions = self.fetch_positions(symbol="BTCUSDT")
        return DemoAccountExposure(tuple(item for item in positions if item.size > 0), ())

    def set_leverage(self, *, symbol: str, leverage: int) -> None:
        assert symbol == "BTCUSDT" and leverage == 100

    def place_market(
        self,
        *,
        order_link_id: str,
        symbol: str,
        side: IntentSide,
        quantity: Decimal,
        reduce_only: bool,
    ) -> DemoOrderAck:
        self.calls.append((side, quantity, reduce_only))
        self.position += quantity if side is IntentSide.BUY else -quantity
        execution = DemoExecution(
            f"exec-{len(self.calls)}",
            order_link_id,
            quantity,
            self.market.price,
            Decimal("0.05"),
            NOW + timedelta(seconds=len(self.calls)),
        )
        self.executions[order_link_id] = (execution,)
        self.orders[order_link_id] = DemoOrderSnapshot(
            f"order-{len(self.calls)}",
            order_link_id,
            symbol,
            DemoOrderStatus.FILLED,
            quantity,
            NOW + timedelta(seconds=len(self.calls)),
            None,
        )
        return DemoOrderAck(f"order-{len(self.calls)}", order_link_id)

    def fetch_positions(self, *, symbol: str) -> tuple[DemoPositionSnapshot, ...]:
        side = "Buy" if self.position > 0 else "Sell" if self.position < 0 else None
        return (DemoPositionSnapshot(symbol, 0, side, abs(self.position), Decimal("100")),)

    def open_order_count(self, *, symbol: str) -> int:
        return 0

    def fetch_order(self, *, order_link_id: str, symbol: str) -> DemoOrderSnapshot | None:
        return self.orders.get(order_link_id)

    def fetch_executions(self, *, order_link_id: str, symbol: str) -> tuple[DemoExecution, ...]:
        return self.executions.get(order_link_id, ())

    def place_post_only(self, **kwargs: object) -> DemoOrderAck:
        raise AssertionError

    def cancel(self, **kwargs: object) -> DemoOrderAck:
        raise AssertionError


class LagGateway(Gateway):
    def place_market(
        self,
        *,
        order_link_id: str,
        symbol: str,
        side: IntentSide,
        quantity: Decimal,
        reduce_only: bool,
    ) -> DemoOrderAck:
        ack = super().place_market(
            order_link_id=order_link_id,
            symbol=symbol,
            side=side,
            quantity=quantity,
            reduce_only=reduce_only,
        )
        self.executions[order_link_id] = ()
        return ack


class PartialExitGateway(Gateway):
    def place_market(
        self,
        *,
        order_link_id: str,
        symbol: str,
        side: IntentSide,
        quantity: Decimal,
        reduce_only: bool,
    ) -> DemoOrderAck:
        if not reduce_only or len(self.calls) != 1:
            return super().place_market(
                order_link_id=order_link_id,
                symbol=symbol,
                side=side,
                quantity=quantity,
                reduce_only=reduce_only,
            )
        filled = quantity / 2
        self.calls.append((side, quantity, reduce_only))
        self.position += filled if side is IntentSide.BUY else -filled
        execution = DemoExecution(
            "exec-partial-exit",
            order_link_id,
            filled,
            self.market.price,
            Decimal("0.025"),
            NOW + timedelta(seconds=len(self.calls)),
        )
        self.executions[order_link_id] = (execution,)
        self.orders[order_link_id] = DemoOrderSnapshot(
            "order-partial-exit",
            order_link_id,
            symbol,
            DemoOrderStatus.CANCELLED,
            filled,
            NOW + timedelta(seconds=len(self.calls)),
            None,
        )
        return DemoOrderAck("order-partial-exit", order_link_id)


def _env() -> dict[str, str]:
    return {
        "TRADING_MODE": "PAPER",
        "BYBIT_DEMO_API_KEY": "demo-key",  # pragma: allowlist secret
        "BYBIT_DEMO_API_SECRET": "demo-secret",  # pragma: allowlist secret
        DEMO_ORDER_CONFIRMATION_ENV_VAR: DEMO_ORDER_CONFIRMATION_VALUE,
        SCALP_CONFIRMATION_ENV_VAR: SCALP_CONFIRMATION_VALUE,
    }


def _executor(tmp_path: Path, gateway: Gateway, market: Market) -> DemoScalpExecutor:
    return DemoScalpExecutor(
        gateway=gateway,
        public_market=market,
        orders=PaperOrderStore(tmp_path / "orders.sqlite3"),
        state=AutonomousDemoStateStore(tmp_path / "state.sqlite3"),
    )


def test_wait_never_places_an_order(tmp_path: Path) -> None:
    market = Market()
    gateway = Gateway(market)
    result = _executor(tmp_path, gateway, market).advance(
        env=_env(),
        symbol="BTCUSDT",
        action=SetupAction.WAIT,
        observation_id="wait-1",
        candidate_id="experimental",
        now_utc=NOW,
    )
    assert result.status == "WAIT"
    assert gateway.calls == []


def test_long_entry_and_stop_are_durable_and_reduce_only(tmp_path: Path) -> None:
    market = Market()
    gateway = Gateway(market)
    executor = _executor(tmp_path, gateway, market)
    opened = executor.advance(
        env=_env(),
        symbol="BTCUSDT",
        action=SetupAction.LONG,
        observation_id="long-1",
        candidate_id="experimental",
        now_utc=NOW,
    )
    assert opened.status == "OPEN"
    assert gateway.calls == [(IntentSide.BUY, Decimal("0.001"), False)]

    market.price = Decimal("99790")
    closed = _executor(tmp_path, gateway, market).advance(
        env=_env(),
        symbol="BTCUSDT",
        action=SetupAction.WAIT,
        observation_id="ignored-after-restart",
        candidate_id="experimental",
        now_utc=NOW + timedelta(seconds=30),
    )
    assert closed.status == "CLOSED"
    assert gateway.position == 0
    assert gateway.calls[-1] == (IntentSide.SELL, Decimal("0.001"), True)


def test_second_entry_same_utc_day_survives_capital_drift(tmp_path: Path) -> None:
    """A closed trade's realized PnL/fees move live account balance - the
    store's daily starting-capital gate must not mistake that ordinary drift
    for a corrupted/changed baseline and refuse the day's next entry."""
    market = Market()
    gateway = Gateway(market)
    executor = _executor(tmp_path, gateway, market)
    opened = executor.advance(
        env=_env(),
        symbol="BTCUSDT",
        action=SetupAction.LONG,
        observation_id="long-1",
        candidate_id="experimental",
        now_utc=NOW,
    )
    assert opened.status == "OPEN"

    market.price = Decimal("99790")
    gateway.balance = Decimal("100.05")  # realized PnL/fees moved live balance
    closed = executor.advance(
        env=_env(),
        symbol="BTCUSDT",
        action=SetupAction.WAIT,
        observation_id="ignored-after-restart",
        candidate_id="experimental",
        now_utc=NOW + timedelta(seconds=30),
    )
    assert closed.status == "CLOSED"

    market.price = Decimal("100000")
    reopened = executor.advance(
        env=_env(),
        symbol="BTCUSDT",
        action=SetupAction.LONG,
        observation_id="long-2",
        candidate_id="experimental",
        now_utc=NOW + timedelta(seconds=400),  # past the 300s cooldown
    )
    assert reopened.status == "OPEN"


def test_execution_feed_lag_is_retried_without_crashing(tmp_path: Path) -> None:
    market = Market()
    gateway = LagGateway(market)
    result = _executor(tmp_path, gateway, market).advance(
        env=_env(),
        symbol="BTCUSDT",
        action=SetupAction.LONG,
        observation_id="lagged-entry",
        candidate_id="experimental",
        now_utc=NOW,
    )
    assert result.status == "ENTRY_SUBMITTED"
    assert "lagging" in result.detail


def test_partial_canceled_exit_submits_residual_after_restart(tmp_path: Path) -> None:
    market = Market()
    gateway = PartialExitGateway(market)
    executor = _executor(tmp_path, gateway, market)
    assert executor.advance(
        env=_env(),
        symbol="BTCUSDT",
        action=SetupAction.LONG,
        observation_id="partial-exit",
        candidate_id="experimental",
        now_utc=NOW,
    ).status == "OPEN"

    market.price = Decimal("99790")
    first_exit = executor.advance(
        env=_env(),
        symbol="BTCUSDT",
        action=SetupAction.WAIT,
        observation_id="ignored",
        candidate_id="experimental",
        now_utc=NOW + timedelta(seconds=30),
    )
    assert first_exit.status == "EXIT_SUBMITTED"
    assert gateway.position == Decimal("0.0005")

    restarted = _executor(tmp_path, gateway, market)
    closed = restarted.advance(
        env=_env(),
        symbol="BTCUSDT",
        action=SetupAction.WAIT,
        observation_id="ignored-again",
        candidate_id="experimental",
        now_utc=NOW + timedelta(seconds=60),
    )
    assert closed.status == "CLOSED"
    assert gateway.position == 0
    assert gateway.calls[-1] == (IntentSide.SELL, Decimal("0.0005"), True)
    assert len(restarted.orders.list_by_leg_group(closed.trade.trade_id)) == 3


def test_preflight_is_cached_for_process_lifetime(tmp_path: Path) -> None:
    market = Market()
    gateway = Gateway(market)
    executor = _executor(tmp_path, gateway, market)
    for suffix in ("one", "two"):
        executor.advance(
            env=_env(),
            symbol="BTCUSDT",
            action=SetupAction.WAIT,
            observation_id=suffix,
            candidate_id="experimental",
            now_utc=NOW,
        )
    assert gateway.preflight_calls == 1
