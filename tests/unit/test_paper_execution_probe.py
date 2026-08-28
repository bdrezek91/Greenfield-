from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest

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
from src.execution.demo_autonomous_state import (
    AutonomousDemoEntryNotAuthorizedError,
    AutonomousDemoStateError,
    AutonomousDemoStateStore,
)
from src.execution.demo_operator import (
    DEMO_ORDER_CONFIRMATION_ENV_VAR,
    DEMO_ORDER_CONFIRMATION_VALUE,
)
from src.execution.execution_probe_journal import ExecutionProbeJournal
from src.execution.intent import IntentSide
from src.execution.paper_execution_probe import (
    HARD_MAXIMUM_NOTIONAL_QUOTE_USD,
    PROBE_CONFIRMATION_ENV_VAR,
    PROBE_CONFIRMATION_VALUE,
    PROBE_LEVERAGE,
    PaperExecutionProbeConfig,
    PaperExecutionProbeExecutor,
    ProbeOrderType,
)
from src.execution.paper_reconciliation import PaperOrderStore

NOW = datetime(2026, 8, 27, 12, 0, tzinfo=UTC)


class FakeClock:
    def __init__(self, start: datetime) -> None:
        self.now = start

    def __call__(self) -> datetime:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.now += timedelta(seconds=seconds)


class Market:
    endpoint = BYBIT_PUBLIC_REST_URL

    def __init__(self) -> None:
        self.price = Decimal("1000")
        self.step = Decimal("0.001")
        self.min_qty = Decimal("0.001")

    def instrument_snapshot(self, *, symbol: str) -> PublicLinearInstrumentSnapshot:
        return PublicLinearInstrumentSnapshot(symbol, self.price, self.step, self.min_qty)

    def funding_snapshot(self, *, symbol: str) -> Any:
        raise NotImplementedError


class Ticker:
    def __init__(
        self, *, bid: Decimal = Decimal("999.5"), ask: Decimal = Decimal("1000.5")
    ) -> None:
        self.bid = bid
        self.ask = ask
        self.calls = 0

    def get_ticker(self, symbol: str, *, category: str = "linear") -> dict[str, Any]:
        self.calls += 1
        return {
            "bid1Price": str(self.bid),
            "ask1Price": str(self.ask),
            "bid1Size": "10",
            "ask1Size": "10",
        }


class Gateway:
    endpoint = BYBIT_DEMO_REST_URL

    def __init__(self, market: Market, clock: FakeClock) -> None:
        self.market = market
        self.clock = clock
        self.position = Decimal("0")
        self.calls: list[tuple[IntentSide, Decimal, bool]] = []
        self.post_only_calls: list[tuple[IntentSide, Decimal, Decimal]] = []
        self.cancel_calls: list[str] = []
        self.orders: dict[str, DemoOrderSnapshot] = {}
        self.executions: dict[str, tuple[DemoExecution, ...]] = {}
        self.preflight_calls = 0
        self._n = 0
        self.reject_post_only = False
        self.post_only_fill_quantity: Decimal | None = None
        self.lag_entry = False

    def preflight(self) -> DemoPreflightReport:
        self.preflight_calls += 1
        return DemoPreflightReport(
            self.endpoint, True, True, True, ("127.0.0.1",), ("Derivatives",), 1, 0, 0
        )

    def account_balance(self) -> DemoAccountBalance:
        return DemoAccountBalance(Decimal(0), Decimal(0), Decimal(0))

    def account_exposure(self) -> DemoAccountExposure:
        positions = self.fetch_positions(symbol="BTCUSDT")
        return DemoAccountExposure(tuple(p for p in positions if p.size > 0), ())

    def set_leverage(self, *, symbol: str, leverage: int) -> None:
        assert leverage == PROBE_LEVERAGE

    def place_market(
        self,
        *,
        order_link_id: str,
        symbol: str,
        side: IntentSide,
        quantity: Decimal,
        reduce_only: bool,
    ) -> DemoOrderAck:
        self._n += 1
        self.calls.append((side, quantity, reduce_only))
        if self.lag_entry and not reduce_only:
            self.orders[order_link_id] = DemoOrderSnapshot(
                f"order-{self._n}",
                order_link_id,
                symbol,
                DemoOrderStatus.FILLED,
                quantity,
                self.clock.now,
                None,
            )
            self.executions[order_link_id] = ()  # feed lag: FILLED but no executions yet
            self.position += quantity if side is IntentSide.BUY else -quantity
            return DemoOrderAck(f"order-{self._n}", order_link_id)
        self.position += quantity if side is IntentSide.BUY else -quantity
        execution = DemoExecution(
            f"exec-{self._n}",
            order_link_id,
            quantity,
            self.market.price,
            Decimal("0.02"),
            self.clock.now,
        )
        self.executions[order_link_id] = (execution,)
        self.orders[order_link_id] = DemoOrderSnapshot(
            f"order-{self._n}",
            order_link_id,
            symbol,
            DemoOrderStatus.FILLED,
            quantity,
            self.clock.now,
            None,
        )
        return DemoOrderAck(f"order-{self._n}", order_link_id)

    def place_post_only(
        self,
        *,
        order_link_id: str,
        symbol: str,
        side: IntentSide,
        quantity: Decimal,
        price: Decimal,
    ) -> DemoOrderAck:
        self._n += 1
        self.post_only_calls.append((side, quantity, price))
        stamp = self.clock.now
        if self.reject_post_only:
            self.orders[order_link_id] = DemoOrderSnapshot(
                f"order-{self._n}",
                order_link_id,
                symbol,
                DemoOrderStatus.REJECTED,
                Decimal(0),
                stamp,
                "would have crossed the spread",
            )
            self.executions[order_link_id] = ()
            return DemoOrderAck(f"order-{self._n}", order_link_id)
        if self.post_only_fill_quantity is not None:
            fill_qty = self.post_only_fill_quantity
            self.position += fill_qty if side is IntentSide.BUY else -fill_qty
            execution = DemoExecution(
                f"exec-{self._n}", order_link_id, fill_qty, price, Decimal("0.01"), stamp
            )
            self.executions[order_link_id] = (execution,)
            status = (
                DemoOrderStatus.FILLED if fill_qty == quantity else DemoOrderStatus.PARTIALLY_FILLED
            )
            self.orders[order_link_id] = DemoOrderSnapshot(
                f"order-{self._n}", order_link_id, symbol, status, fill_qty, stamp, None
            )
        else:
            self.orders[order_link_id] = DemoOrderSnapshot(
                f"order-{self._n}",
                order_link_id,
                symbol,
                DemoOrderStatus.NEW,
                Decimal(0),
                stamp,
                None,
            )
            self.executions[order_link_id] = ()
        return DemoOrderAck(f"order-{self._n}", order_link_id)

    def cancel(self, *, order_link_id: str, symbol: str) -> DemoOrderAck:
        self.cancel_calls.append(order_link_id)
        self._n += 1
        stamp = self.clock.now
        existing = self.orders.get(order_link_id)
        filled = existing.cumulative_filled_quantity if existing else Decimal(0)
        order_id = existing.order_id if existing else f"order-cancel-{len(self.cancel_calls)}"
        self.orders[order_link_id] = DemoOrderSnapshot(
            order_id, order_link_id, symbol, DemoOrderStatus.CANCELLED, filled, stamp, None
        )
        return DemoOrderAck(order_id, order_link_id)

    def fetch_positions(self, *, symbol: str) -> tuple[DemoPositionSnapshot, ...]:
        side = "Buy" if self.position > 0 else "Sell" if self.position < 0 else None
        return (DemoPositionSnapshot(symbol, 0, side, abs(self.position), Decimal("1")),)

    def open_order_count(self, *, symbol: str) -> int:
        return 0

    def fetch_order(self, *, order_link_id: str, symbol: str) -> DemoOrderSnapshot | None:
        return self.orders.get(order_link_id)

    def fetch_executions(self, *, order_link_id: str, symbol: str) -> tuple[DemoExecution, ...]:
        return self.executions.get(order_link_id, ())


def _env() -> dict[str, str]:
    return {
        "TRADING_MODE": "PAPER",
        "BYBIT_DEMO_API_KEY": "demo-key",  # pragma: allowlist secret
        "BYBIT_DEMO_API_SECRET": "demo-secret",  # pragma: allowlist secret
        DEMO_ORDER_CONFIRMATION_ENV_VAR: DEMO_ORDER_CONFIRMATION_VALUE,
        PROBE_CONFIRMATION_ENV_VAR: PROBE_CONFIRMATION_VALUE,
    }


def _config(**overrides: object) -> PaperExecutionProbeConfig:
    defaults: dict[str, object] = dict(
        target_notional_quote_usd=Decimal("30"),
        maximum_notional_quote_usd=Decimal("60"),
        maker_fill_timeout_seconds=5,
        maximum_orders_per_utc_day=12,
        cooldown_seconds=5,
        maximum_daily_loss_usd=Decimal("10"),
        markout_horizons_seconds=(0.1, 0.25, 0.5),
        reconcile_poll_seconds=1.0,
        reconcile_timeout_seconds=5.0,
    )
    defaults.update(overrides)
    return PaperExecutionProbeConfig(**defaults)  # type: ignore[arg-type]


def _executor(
    tmp_path: Path,
    gateway: Gateway,
    market: Market,
    ticker: Ticker,
    clock: FakeClock,
    *,
    config: PaperExecutionProbeConfig | None = None,
) -> PaperExecutionProbeExecutor:
    return PaperExecutionProbeExecutor(
        gateway=gateway,
        public_market=market,
        ticker=ticker,
        orders=PaperOrderStore(tmp_path / "orders.sqlite3"),
        state=AutonomousDemoStateStore(tmp_path / "state.sqlite3"),
        journal=ExecutionProbeJournal(tmp_path / "journal.sqlite3"),
        config=config or _config(),
        clock=clock,
        sleep=clock.sleep,
    )


def test_gateway_must_be_pinned_to_bybit_demo(tmp_path: Path) -> None:
    market = Market()
    gateway = Gateway(market, FakeClock(NOW))
    gateway.endpoint = "https://api.bybit.com"
    with pytest.raises(ValueError, match="pinned to Bybit Demo"):
        PaperExecutionProbeExecutor(
            gateway=gateway,
            public_market=market,
            ticker=Ticker(),
            orders=PaperOrderStore(tmp_path / "orders.sqlite3"),
            state=AutonomousDemoStateStore(tmp_path / "state.sqlite3"),
            journal=ExecutionProbeJournal(tmp_path / "journal.sqlite3"),
        )


def test_confirmation_gate_requires_both_order_and_probe_confirmation(tmp_path: Path) -> None:
    market = Market()
    clock = FakeClock(NOW)
    gateway = Gateway(market, clock)
    executor = _executor(tmp_path, gateway, market, Ticker(), clock)
    env = _env()
    del env[PROBE_CONFIRMATION_ENV_VAR]
    with pytest.raises(ValueError, match=PROBE_CONFIRMATION_ENV_VAR):
        executor.run(env=env, symbol="BTCUSDT", request_id="req-1", now_utc=NOW)
    assert gateway.calls == []
    assert gateway.post_only_calls == []


def test_unowned_exposure_blocks_a_new_probe(tmp_path: Path) -> None:
    market = Market()
    clock = FakeClock(NOW)
    gateway = Gateway(market, clock)
    gateway.position = Decimal("0.01")  # pre-existing, unattributed exposure
    executor = _executor(tmp_path, gateway, market, Ticker(), clock)
    with pytest.raises(AutonomousDemoStateError, match="unowned Demo exposure"):
        executor.run(env=_env(), symbol="BTCUSDT", request_id="req-1", now_utc=NOW)


def test_taker_entry_fills_flattens_immediately_and_journals_evidence(tmp_path: Path) -> None:
    market = Market()
    clock = FakeClock(NOW)
    gateway = Gateway(market, clock)
    ticker = Ticker()
    executor = _executor(tmp_path, gateway, market, ticker, clock)
    result = executor.run(
        env=_env(),
        symbol="BTCUSDT",
        request_id="taker-1",
        now_utc=NOW,
        mode_override=ProbeOrderType.TAKER,
        side_override=IntentSide.BUY,
    )
    assert result.status == "CLOSED"
    assert gateway.position == 0
    assert gateway.calls[0] == (IntentSide.BUY, Decimal("0.030"), False)
    assert gateway.calls[-1] == (IntentSide.SELL, Decimal("0.030"), True)
    assert gateway.post_only_calls == []

    observations = ExecutionProbeJournal(tmp_path / "journal.sqlite3").load_observations()
    assert len(observations) == 1
    obs = observations[0]
    assert obs.symbol == "BTCUSDT"
    assert obs.venue == "bybit-demo"
    assert obs.rejected is False
    assert obs.filled_quantity == pytest.approx(0.030)

    labels = {("T+0.1s"), ("T+0.25s"), ("T+0.5s"), ("REFERENCE")}
    assert labels.issubset(_quote_labels(tmp_path))


def _quote_labels(tmp_path: Path) -> set[str]:
    import sqlite3

    connection = sqlite3.connect(tmp_path / "journal.sqlite3")
    rows = connection.execute("SELECT horizon_label FROM execution_probe_quotes").fetchall()
    connection.close()
    return {row[0] for row in rows}


def test_maker_entry_that_never_fills_is_canceled_with_no_exposure_left(tmp_path: Path) -> None:
    market = Market()
    clock = FakeClock(NOW)
    gateway = Gateway(market, clock)  # never fills post-only orders by default
    ticker = Ticker()
    executor = _executor(tmp_path, gateway, market, ticker, clock)
    result = executor.run(
        env=_env(),
        symbol="BTCUSDT",
        request_id="maker-miss-1",
        now_utc=NOW,
        mode_override=ProbeOrderType.MAKER,
        side_override=IntentSide.BUY,
    )
    assert result.status == "CLOSED_NO_FILL"
    assert gateway.position == 0
    assert len(gateway.cancel_calls) == 1
    assert gateway.calls == []  # never touched a market/reduce-only order

    observations = ExecutionProbeJournal(tmp_path / "journal.sqlite3").load_observations()
    assert len(observations) == 1
    assert observations[0].rejected is True
    assert observations[0].filled_quantity == 0


def test_maker_entry_partial_fill_before_timeout_is_flattened(tmp_path: Path) -> None:
    market = Market()
    clock = FakeClock(NOW)
    gateway = Gateway(market, clock)
    gateway.post_only_fill_quantity = Decimal("0.015")  # half of the 0.030 target
    ticker = Ticker()
    executor = _executor(tmp_path, gateway, market, ticker, clock)
    result = executor.run(
        env=_env(),
        symbol="BTCUSDT",
        request_id="maker-partial-1",
        now_utc=NOW,
        mode_override=ProbeOrderType.MAKER,
        side_override=IntentSide.SELL,
    )
    assert result.status == "CLOSED"
    assert gateway.position == 0
    assert len(gateway.cancel_calls) == 1
    assert gateway.calls[-1] == (IntentSide.BUY, Decimal("0.015"), True)

    observations = ExecutionProbeJournal(tmp_path / "journal.sqlite3").load_observations()
    assert observations[0].rejected is False
    assert observations[0].filled_quantity == pytest.approx(0.015)


def test_maker_entry_that_would_cross_is_cleanly_rejected(tmp_path: Path) -> None:
    market = Market()
    clock = FakeClock(NOW)
    gateway = Gateway(market, clock)
    gateway.reject_post_only = True
    ticker = Ticker()
    executor = _executor(tmp_path, gateway, market, ticker, clock)
    result = executor.run(
        env=_env(),
        symbol="BTCUSDT",
        request_id="maker-rejected-1",
        now_utc=NOW,
        mode_override=ProbeOrderType.MAKER,
        side_override=IntentSide.BUY,
    )
    assert result.status == "CLOSED_NO_FILL"
    assert gateway.position == 0
    assert gateway.cancel_calls == []  # a hard rejection needs no cancel


def test_execution_feed_lag_does_not_resubmit_on_resume(tmp_path: Path) -> None:
    market = Market()
    clock = FakeClock(NOW)
    gateway = Gateway(market, clock)
    gateway.lag_entry = True
    ticker = Ticker()
    first = _executor(tmp_path, gateway, market, ticker, clock)
    pending = first.run(
        env=_env(),
        symbol="BTCUSDT",
        request_id="lagged-1",
        now_utc=NOW,
        mode_override=ProbeOrderType.TAKER,
        side_override=IntentSide.BUY,
    )
    assert pending.status == "PENDING_RECONCILIATION"
    assert len(gateway.calls) == 1  # entry was submitted exactly once

    # The execution feed "catches up".
    for link_id in list(gateway.executions.keys()):
        order = gateway.orders[link_id]
        if order.status is DemoOrderStatus.FILLED and not gateway.executions[link_id]:
            gateway.executions[link_id] = (
                DemoExecution(
                    "exec-late", link_id, order.cumulative_filled_quantity, market.price,
                    Decimal("0.02"), NOW,
                ),
            )

    clock.now += timedelta(seconds=1)
    second = _executor(tmp_path, gateway, market, ticker, clock)
    resumed = second.run(
        env=_env(),
        symbol="BTCUSDT",
        request_id="lagged-1",
        now_utc=clock.now,
        mode_override=ProbeOrderType.TAKER,
        side_override=IntentSide.BUY,
    )
    assert resumed.status == "CLOSED"
    assert len(gateway.calls) == 2  # entry + exit only, never a duplicate entry
    assert gateway.position == 0


def test_reused_request_id_at_a_different_price_never_resubmits(tmp_path: Path) -> None:
    market = Market()
    clock = FakeClock(NOW)
    gateway = Gateway(market, clock)
    ticker = Ticker()
    executor = _executor(
        tmp_path, gateway, market, ticker, clock, config=_config(cooldown_seconds=0)
    )
    first = executor.run(
        env=_env(),
        symbol="BTCUSDT",
        request_id="req-reuse",
        now_utc=NOW,
        mode_override=ProbeOrderType.TAKER,
        side_override=IntentSide.BUY,
    )
    assert first.status == "CLOSED"
    calls_after_first = len(gateway.calls)

    ticker.bid = Decimal("1999.5")  # market moved: a recomputed reference price would differ
    ticker.ask = Decimal("2000.5")
    second = executor.run(
        env=_env(),
        symbol="BTCUSDT",
        request_id="req-reuse",
        now_utc=NOW + timedelta(seconds=1),
        mode_override=ProbeOrderType.TAKER,
        side_override=IntentSide.BUY,
    )
    assert second.status == "REQUEST_ID_ALREADY_RESOLVED"
    assert len(gateway.calls) == calls_after_first  # no new order was ever placed


def test_daily_order_count_cap_is_enforced_and_reused_from_existing_state_store(
    tmp_path: Path,
) -> None:
    market = Market()
    clock = FakeClock(NOW)
    gateway = Gateway(market, clock)
    ticker = Ticker()
    executor = _executor(tmp_path, gateway, market, ticker, clock, config=_config(
        maximum_orders_per_utc_day=1, cooldown_seconds=0
    ))
    first = executor.run(
        env=_env(),
        symbol="BTCUSDT",
        request_id="cap-1",
        now_utc=NOW,
        mode_override=ProbeOrderType.TAKER,
        side_override=IntentSide.BUY,
    )
    assert first.status == "CLOSED"
    with pytest.raises(AutonomousDemoEntryNotAuthorizedError):
        executor.run(
            env=_env(),
            symbol="BTCUSDT",
            request_id="cap-2",
            now_utc=NOW + timedelta(seconds=1),
            mode_override=ProbeOrderType.TAKER,
            side_override=IntentSide.BUY,
        )


def test_hard_notional_ceiling_cannot_be_configured_higher(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="at most"):
        PaperExecutionProbeConfig(
            maximum_notional_quote_usd=HARD_MAXIMUM_NOTIONAL_QUOTE_USD + Decimal("1")
        )


def test_symbol_minimum_notional_above_cap_fails_closed_before_any_order(tmp_path: Path) -> None:
    market = Market()
    market.min_qty = Decimal("1")  # 1 * price(1000) = 1000 USDT, far above the 60 USDT cap
    clock = FakeClock(NOW)
    gateway = Gateway(market, clock)
    ticker = Ticker()
    executor = _executor(tmp_path, gateway, market, ticker, clock)
    with pytest.raises(ValueError, match="minimum tradable notional"):
        executor.run(
            env=_env(),
            symbol="BTCUSDT",
            request_id="too-big-1",
            now_utc=NOW,
            mode_override=ProbeOrderType.TAKER,
            side_override=IntentSide.BUY,
        )
    assert gateway.calls == []
    assert gateway.post_only_calls == []


def test_mode_and_side_alternate_deterministically_without_override(tmp_path: Path) -> None:
    market = Market()
    clock = FakeClock(NOW)
    gateway = Gateway(market, clock)
    gateway.post_only_fill_quantity = Decimal("0.030")  # maker orders fill fully in this test
    ticker = Ticker()
    executor = _executor(tmp_path, gateway, market, ticker, clock)
    seen: list[tuple[bool, IntentSide]] = []
    for i in range(4):
        before_market_calls = len(gateway.calls)
        before_maker_calls = len(gateway.post_only_calls)
        executor.run(
            env=_env(), symbol="BTCUSDT", request_id=f"cycle-{i}", now_utc=clock.now
        )
        used_maker = len(gateway.post_only_calls) > before_maker_calls
        # A market order is placed every cycle (the reduce-only flatten), plus one more
        # for a TAKER entry - so entry mode is determined by post_only_calls alone.
        side = (
            gateway.post_only_calls[-1][0]
            if used_maker
            else gateway.calls[before_market_calls][0]
        )
        seen.append((used_maker, side))
        clock.now += timedelta(seconds=10)
    assert seen == [
        (False, IntentSide.BUY),
        (False, IntentSide.SELL),
        (True, IntentSide.BUY),
        (True, IntentSide.SELL),
    ]
