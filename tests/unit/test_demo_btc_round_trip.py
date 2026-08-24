from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

import pytest

from src.execution.bybit_demo_gateway import (
    BYBIT_DEMO_REST_URL,
    BYBIT_PUBLIC_REST_URL,
    DemoExecution,
    DemoOrderAck,
    DemoOrderSnapshot,
    DemoOrderStatus,
    DemoPositionSnapshot,
    DemoPreflightReport,
    PublicLinearInstrumentSnapshot,
)
from src.execution.demo_btc_round_trip import (
    BTC_ROUND_TRIP_CONFIRMATION_ENV_VAR,
    BTC_ROUND_TRIP_CONFIRMATION_VALUE,
    DemoBtcRoundTripCoordinator,
    DemoBtcRoundTripPhase,
    DemoBtcRoundTripRequest,
)
from src.execution.demo_operator import (
    DEMO_ORDER_CONFIRMATION_ENV_VAR,
    DEMO_ORDER_CONFIRMATION_VALUE,
)
from src.execution.intent import IntentSide
from src.execution.paper_reconciliation import PaperOrderState, PaperOrderStore

NOW = datetime(2026, 8, 24, 18, tzinfo=UTC)


def _env() -> dict[str, str]:
    return {
        "TRADING_MODE": "PAPER",
        "BYBIT_DEMO_API_KEY": "demo-key",  # pragma: allowlist secret
        "BYBIT_DEMO_API_SECRET": "demo-secret",  # pragma: allowlist secret
        DEMO_ORDER_CONFIRMATION_ENV_VAR: DEMO_ORDER_CONFIRMATION_VALUE,
        BTC_ROUND_TRIP_CONFIRMATION_ENV_VAR: BTC_ROUND_TRIP_CONFIRMATION_VALUE,
    }


class FakePublicMarket:
    endpoint = BYBIT_PUBLIC_REST_URL

    def __init__(self, *, price: Decimal = Decimal("100000")) -> None:
        self.price = price

    def instrument_snapshot(self, *, symbol: str) -> PublicLinearInstrumentSnapshot:
        return PublicLinearInstrumentSnapshot(
            symbol=symbol,
            last_price=self.price,
            quantity_step=Decimal("0.001"),
            minimum_order_quantity=Decimal("0.001"),
        )


class FakeRoundTripGateway:
    endpoint = BYBIT_DEMO_REST_URL

    def __init__(self) -> None:
        self.position = Decimal("0")
        self.position_index = 0
        self.pre_existing_open_orders = 0
        self.place_calls: list[tuple[IntentSide, Decimal, bool, str]] = []
        self.leverage_calls: list[tuple[str, int]] = []
        self.orders: dict[str, DemoOrderSnapshot] = {}
        self.executions: dict[str, tuple[DemoExecution, ...]] = {}
        self.fail_next_place = False

    def preflight(self) -> DemoPreflightReport:
        return DemoPreflightReport(
            self.endpoint,
            True,
            True,
            True,
            ("57.128.220.89",),
            ("Derivatives", "Options", "Spot"),
            1,
            0,
            self.pre_existing_open_orders,
        )

    def set_leverage(self, *, symbol: str, leverage: int) -> None:
        self.leverage_calls.append((symbol, leverage))

    def place_market(
        self,
        *,
        order_link_id: str,
        symbol: str,
        side: IntentSide,
        quantity: Decimal,
        reduce_only: bool,
    ) -> DemoOrderAck:
        self.place_calls.append((side, quantity, reduce_only, order_link_id))
        if self.fail_next_place:
            self.fail_next_place = False
            raise ConnectionError("ambiguous transport failure")
        if side is IntentSide.BUY:
            self.position += quantity
        else:
            assert reduce_only
            self.position = max(Decimal("0"), self.position - quantity)
        self.executions[order_link_id] = (
            DemoExecution(
                execution_id=f"exec-{len(self.place_calls)}",
                order_link_id=order_link_id,
                quantity=quantity,
                price=Decimal("100000"),
                fee_quote=Decimal("0.055"),
                executed_at_utc=NOW,
            ),
        )
        self.orders[order_link_id] = DemoOrderSnapshot(
            order_id=f"order-{len(self.place_calls)}",
            order_link_id=order_link_id,
            symbol=symbol,
            status=DemoOrderStatus.FILLED,
            cumulative_filled_quantity=quantity,
            updated_at_utc=NOW,
            reject_reason=None,
        )
        return DemoOrderAck(f"order-{len(self.place_calls)}", order_link_id)

    def fetch_positions(self, *, symbol: str) -> tuple[DemoPositionSnapshot, ...]:
        return (
            DemoPositionSnapshot(
                symbol=symbol,
                position_index=self.position_index,
                side="Buy" if self.position else None,
                size=self.position,
                leverage=Decimal("100"),
            ),
        )

    def open_order_count(self, *, symbol: str) -> int:
        del symbol
        return self.pre_existing_open_orders

    def fetch_order(
        self, *, order_link_id: str, symbol: str
    ) -> DemoOrderSnapshot | None:
        del symbol
        return self.orders.get(order_link_id)

    def fetch_executions(
        self, *, order_link_id: str, symbol: str
    ) -> tuple[DemoExecution, ...]:
        del symbol
        return self.executions.get(order_link_id, ())

    def place_post_only(self, **kwargs: object) -> DemoOrderAck:
        raise AssertionError("round-trip must not place a limit order")

    def cancel(self, **kwargs: object) -> DemoOrderAck:
        raise AssertionError("round-trip must not cancel a market order")


def _coordinator(
    tmp_path: Path,
    gateway: FakeRoundTripGateway,
    *,
    public_market: FakePublicMarket | None = None,
) -> DemoBtcRoundTripCoordinator:
    return DemoBtcRoundTripCoordinator(
        gateway=gateway,
        public_market=public_market or FakePublicMarket(),
        store=PaperOrderStore(tmp_path / "round-trip.sqlite3"),
    )


def test_round_trip_buys_then_reduce_only_closes_and_finishes_flat(
    tmp_path: Path,
) -> None:
    gateway = FakeRoundTripGateway()
    result = _coordinator(tmp_path, gateway).advance(
        DemoBtcRoundTripRequest("btc-demo-001"), env=_env(), now_utc=NOW
    )

    assert result.phase is DemoBtcRoundTripPhase.COMPLETE
    assert result.submitted_quantity == Decimal("0.001")
    assert result.estimated_entry_notional_quote == Decimal("100.000")
    assert gateway.leverage_calls == [("BTCUSDT", 100)]
    assert [(call[0], call[2]) for call in gateway.place_calls] == [
        (IntentSide.BUY, False),
        (IntentSide.SELL, True),
    ]
    assert result.entry_order.state is PaperOrderState.FILLED
    assert result.close_orders[-1].state is PaperOrderState.FILLED
    assert result.exchange_position_size == 0
    assert result.paper_position is not None
    assert result.paper_position.net_quantity == pytest.approx(0)


def test_ambiguous_entry_is_durable_and_never_resent(tmp_path: Path) -> None:
    gateway = FakeRoundTripGateway()
    coordinator = _coordinator(tmp_path, gateway)
    gateway.fail_next_place = True

    with pytest.raises(ConnectionError, match="ambiguous"):
        coordinator.advance(
            DemoBtcRoundTripRequest("btc-demo-ambiguous"), env=_env(), now_utc=NOW
        )
    restarted = _coordinator(tmp_path, gateway)
    result = restarted.advance(
        DemoBtcRoundTripRequest("btc-demo-ambiguous"), env=_env(), now_utc=NOW
    )

    assert result.phase is DemoBtcRoundTripPhase.ENTRY_UNRESOLVED
    assert result.entry_order.state is PaperOrderState.SUBMITTED
    assert len(gateway.place_calls) == 1


@pytest.mark.parametrize(
    ("missing", "message"),
    [
        (DEMO_ORDER_CONFIRMATION_ENV_VAR, "Demo order submission requires"),
        (BTC_ROUND_TRIP_CONFIRMATION_ENV_VAR, "BTC Demo round-trip requires"),
    ],
)
def test_both_exact_confirmations_are_required_before_network(
    tmp_path: Path, missing: str, message: str
) -> None:
    gateway = FakeRoundTripGateway()
    env = _env()
    del env[missing]

    with pytest.raises(ValueError, match=message):
        _coordinator(tmp_path, gateway).advance(
            DemoBtcRoundTripRequest("btc-demo-unarmed"), env=env, now_utc=NOW
        )
    assert gateway.leverage_calls == []
    assert gateway.place_calls == []


@pytest.mark.parametrize("unsafe_state", ["position", "orders"])
def test_pre_existing_exposure_fails_before_submission(
    tmp_path: Path, unsafe_state: str
) -> None:
    gateway = FakeRoundTripGateway()
    if unsafe_state == "position":
        gateway.position = Decimal("0.001")
    else:
        gateway.pre_existing_open_orders = 1

    with pytest.raises(RuntimeError, match="pre-existing|not flat"):
        _coordinator(tmp_path, gateway).advance(
            DemoBtcRoundTripRequest(f"btc-demo-{unsafe_state}"),
            env=_env(),
            now_utc=NOW,
        )
    assert gateway.leverage_calls == []
    assert gateway.place_calls == []


def test_oversized_minimum_quantity_is_rejected_before_private_order(
    tmp_path: Path,
) -> None:
    gateway = FakeRoundTripGateway()
    with pytest.raises(ValueError, match="75-125"):
        _coordinator(
            tmp_path,
            gateway,
            public_market=FakePublicMarket(price=Decimal("130000")),
        ).advance(DemoBtcRoundTripRequest("btc-demo-too-large"), env=_env(), now_utc=NOW)
    assert gateway.place_calls == []


def test_hedge_mode_and_unexpected_short_are_fail_closed(tmp_path: Path) -> None:
    hedge_gateway = FakeRoundTripGateway()
    hedge_gateway.position_index = 1
    with pytest.raises(RuntimeError, match="one-way"):
        _coordinator(tmp_path, hedge_gateway).advance(
            DemoBtcRoundTripRequest("btc-demo-hedge"), env=_env(), now_utc=NOW
        )

    short_gateway = FakeRoundTripGateway()
    short_gateway.position = Decimal("0.001")
    original_fetch = short_gateway.fetch_positions

    def _short(*, symbol: str) -> tuple[DemoPositionSnapshot, ...]:
        row = original_fetch(symbol=symbol)[0]
        return (DemoPositionSnapshot(symbol, 0, "Sell", row.size, row.leverage),)

    short_gateway.fetch_positions = _short  # type: ignore[method-assign]
    with pytest.raises(RuntimeError, match="unexpected short"):
        _coordinator(tmp_path, short_gateway).advance(
            DemoBtcRoundTripRequest("btc-demo-short"), env=_env(), now_utc=NOW
        )
