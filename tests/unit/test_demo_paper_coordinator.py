from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import pytest

from src.execution.bybit_demo_gateway import (
    BYBIT_DEMO_REST_URL,
    DemoExecution,
    DemoOrderAck,
    DemoOrderSnapshot,
    DemoOrderStatus,
    DemoPreflightReport,
)
from src.execution.demo_paper_coordinator import (
    DemoPaperCoordinator,
    demo_order_link_id_for,
)
from src.execution.intent import IntentSide
from src.execution.paper_reconciliation import PaperOrderState, PaperOrderStore
from src.risk.portfolio_engine import PortfolioEntryProposal

NOW = datetime(2026, 8, 24, 20, tzinfo=UTC)


class FakeDemoGateway:
    endpoint = BYBIT_DEMO_REST_URL

    def __init__(self) -> None:
        self.place_calls = 0
        self.cancel_calls = 0
        self.executions: tuple[DemoExecution, ...] = ()
        self.order: DemoOrderSnapshot | None = None
        self.on_place: object | None = None

    def preflight(self) -> DemoPreflightReport:
        return DemoPreflightReport(
            self.endpoint,
            True,
            True,
            True,
            ("57.128.220.89",),
            1,
            0,
            0,
        )

    def place_post_only(
        self,
        *,
        order_link_id: str,
        symbol: str,
        side: IntentSide,
        quantity: Decimal,
        price: Decimal,
    ) -> DemoOrderAck:
        del symbol, side, quantity, price
        self.place_calls += 1
        if callable(self.on_place):
            self.on_place()
        return DemoOrderAck("exchange-1", order_link_id)

    def cancel(self, *, order_link_id: str, symbol: str) -> DemoOrderAck:
        del symbol
        self.cancel_calls += 1
        return DemoOrderAck("exchange-1", order_link_id)

    def fetch_order(
        self, *, order_link_id: str, symbol: str
    ) -> DemoOrderSnapshot | None:
        del order_link_id, symbol
        return self.order

    def fetch_executions(
        self, *, order_link_id: str, symbol: str
    ) -> tuple[DemoExecution, ...]:
        del order_link_id, symbol
        return self.executions


def _proposal(**overrides: object) -> PortfolioEntryProposal:
    values: dict[str, object] = {
        "key": "observation-1:leg-0",
        "symbol": "ETHUSDT",
        "venue": "bybit",
        "strategy": "directional-v1",
        "engine": "directional",
        "signed_notional": 1_000.0,
        "committed_risk_fraction": 0.005,
        "correlation_checked_symbols": (),
        "correlated_symbols": (),
        "proposed_at_utc": NOW,
    }
    values.update(overrides)
    return PortfolioEntryProposal(**values)  # type: ignore[arg-type]


def _coordinator(tmp_path: Path, gateway: FakeDemoGateway) -> DemoPaperCoordinator:
    return DemoPaperCoordinator(
        gateway=gateway,
        store=PaperOrderStore(tmp_path / "orders.sqlite3"),
    )


def test_submit_is_write_ahead_and_idempotent_across_restart(tmp_path: Path) -> None:
    gateway = FakeDemoGateway()
    coordinator = _coordinator(tmp_path, gateway)
    observed_states: list[PaperOrderState] = []

    def _observe_state() -> None:
        record = coordinator.store.get_by_idempotency_key(
            "observation-1:leg-0:bybit-demo-v1"
        )
        assert record is not None
        observed_states.append(record.state)

    gateway.on_place = _observe_state
    first = coordinator.submit_proposal(
        _proposal(),
        demo_notional_quote=Decimal("30"),
        reference_price=Decimal("3000"),
        limit_price=Decimal("2990"),
        now_utc=NOW,
    )
    restarted = DemoPaperCoordinator(
        gateway=gateway,
        store=PaperOrderStore(tmp_path / "orders.sqlite3"),
    )
    second = restarted.submit_proposal(
        _proposal(),
        demo_notional_quote=Decimal("30"),
        reference_price=Decimal("3000"),
        limit_price=Decimal("2990"),
        now_utc=NOW + timedelta(seconds=1),
    )

    assert observed_states == [PaperOrderState.SUBMITTED]
    assert first.submitted_now and not second.submitted_now
    assert first.order_link_id == second.order_link_id
    assert len(first.order_link_id) == 36
    assert gateway.place_calls == 1


def test_unknown_network_outcome_stays_ambiguous_and_is_not_resent(tmp_path: Path) -> None:
    gateway = FakeDemoGateway()
    coordinator = _coordinator(tmp_path, gateway)

    def _fail() -> None:
        raise ConnectionError("ambiguous transport failure")

    gateway.on_place = _fail
    with pytest.raises(ConnectionError, match="ambiguous"):
        coordinator.submit_proposal(
            _proposal(),
            demo_notional_quote=Decimal("30"),
            reference_price=Decimal("3000"),
            limit_price=Decimal("2990"),
            now_utc=NOW,
        )
    record = coordinator.store.get_by_idempotency_key(
        "observation-1:leg-0:bybit-demo-v1"
    )
    assert record is not None and record.state is PaperOrderState.SUBMITTED

    gateway.on_place = None
    replay = coordinator.submit_proposal(
        _proposal(),
        demo_notional_quote=Decimal("30"),
        reference_price=Decimal("3000"),
        limit_price=Decimal("2990"),
        now_utc=NOW + timedelta(seconds=1),
    )
    assert not replay.submitted_now
    assert gateway.place_calls == 1


def test_partial_fill_then_confirmed_cancel_reconciles_durably(tmp_path: Path) -> None:
    gateway = FakeDemoGateway()
    coordinator = _coordinator(tmp_path, gateway)
    submitted = coordinator.submit_proposal(
        _proposal(),
        demo_notional_quote=Decimal("30"),
        reference_price=Decimal("3000"),
        limit_price=Decimal("2990"),
        now_utc=NOW,
    )
    gateway.executions = (
        DemoExecution(
            execution_id="exec-1",
            order_link_id=submitted.order_link_id,
            quantity=Decimal("0.005"),
            price=Decimal("3001"),
            fee_quote=Decimal("0.01"),
            executed_at_utc=NOW + timedelta(seconds=1),
        ),
    )
    gateway.order = DemoOrderSnapshot(
        order_id="exchange-1",
        order_link_id=submitted.order_link_id,
        symbol="ETHUSDT",
        status=DemoOrderStatus.CANCELLED,
        cumulative_filled_quantity=Decimal("0.005"),
        updated_at_utc=NOW + timedelta(seconds=2),
        reject_reason=None,
    )

    result = coordinator.cancel_and_reconcile(submitted.paper_order.client_order_id)
    replay = coordinator.reconcile(submitted.paper_order.client_order_id)

    assert result.paper_order.state is PaperOrderState.CANCELED
    assert result.paper_order.filled_quantity == pytest.approx(0.005)
    assert result.paper_order.slippage_cost_quote == pytest.approx(0.005)
    assert result.paper_order.fee_cost_quote == pytest.approx(0.01)
    assert replay.paper_order == result.paper_order
    assert gateway.cancel_calls == 1
    assert len(coordinator.store.list_fills(result.paper_order.client_order_id)) == 1


@pytest.mark.parametrize(
    ("proposal", "now", "message"),
    [
        (_proposal(venue="binance"), NOW, "only Bybit"),
        (_proposal(symbol="XRPUSDT"), NOW, "not allowed"),
        (_proposal(proposed_at_utc=NOW - timedelta(seconds=31)), NOW, "stale"),
        (_proposal(proposed_at_utc=NOW + timedelta(seconds=1)), NOW, "future"),
    ],
)
def test_proposal_safety_gates_fail_before_network(
    tmp_path: Path,
    proposal: PortfolioEntryProposal,
    now: datetime,
    message: str,
) -> None:
    gateway = FakeDemoGateway()
    coordinator = _coordinator(tmp_path, gateway)
    with pytest.raises(ValueError, match=message):
        coordinator.submit_proposal(
            proposal,
            demo_notional_quote=Decimal("30"),
            reference_price=Decimal("3000"),
            limit_price=Decimal("2990"),
            now_utc=now,
        )
    assert gateway.place_calls == 0


def test_gateway_endpoint_and_order_bounds_are_fail_closed(tmp_path: Path) -> None:
    gateway = FakeDemoGateway()
    gateway.endpoint = "https://api.bybit.com"
    with pytest.raises(ValueError, match="Demo endpoint"):
        _coordinator(tmp_path, gateway)

    safe_gateway = FakeDemoGateway()
    coordinator = _coordinator(tmp_path, safe_gateway)
    with pytest.raises(ValueError, match="bounded allocation"):
        coordinator.submit_proposal(
            _proposal(),
            demo_notional_quote=Decimal("251"),
            reference_price=Decimal("3000"),
            limit_price=Decimal("2990"),
            now_utc=NOW,
        )
    with pytest.raises(ValueError, match="deviation"):
        coordinator.submit_proposal(
            _proposal(key="observation-2:leg-0"),
            demo_notional_quote=Decimal("30"),
            reference_price=Decimal("3000"),
            limit_price=Decimal("2800"),
            now_utc=NOW,
        )
    with pytest.raises(ValueError, match="BUY smoke limit"):
        coordinator.submit_proposal(
            _proposal(key="observation-3:leg-0"),
            demo_notional_quote=Decimal("30"),
            reference_price=Decimal("3000"),
            limit_price=Decimal("3000"),
            now_utc=NOW,
        )
    with pytest.raises(ValueError, match="SELL smoke limit"):
        coordinator.submit_proposal(
            _proposal(key="observation-4:leg-0", signed_notional=-1_000.0),
            demo_notional_quote=Decimal("30"),
            reference_price=Decimal("3000"),
            limit_price=Decimal("2990"),
            now_utc=NOW,
        )
    assert safe_gateway.place_calls == 0


def test_order_link_mapping_is_stable_bounded_and_distinct() -> None:
    first = demo_order_link_id_for("paper-one")
    assert first == demo_order_link_id_for("paper-one")
    assert first != demo_order_link_id_for("paper-two")
    assert len(first) == 36
    assert first.startswith("gfd-")
