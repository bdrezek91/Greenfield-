"""Durability, idempotency, and correctness tests for PAPER order/fill/
position reconciliation."""

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from src.execution.adapter import Fill
from src.execution.intent import IntentSide, OrderIntent
from src.execution.paper_reconciliation import (
    LegGroupStatus,
    PaperOrderState,
    PaperOrderStore,
    PaperReconciliationError,
    client_order_id_for,
)

NOW = datetime(2026, 8, 23, 18, tzinfo=UTC)


def _intent(symbol: str = "BTCUSDT", side: IntentSide = IntentSide.BUY) -> OrderIntent:
    return OrderIntent(
        symbol=symbol, side=side, quantity=1.0, reference_price=50_000.0, created_at=NOW
    )


def _fill(
    *,
    quantity: float,
    price: float,
    at: datetime = NOW,
    rejected: bool = False,
    reject_reason: str = "",
    spread: float = 0.0,
    slippage: float = 0.0,
    fee: float = 0.0,
    funding: float = 0.0,
) -> Fill:
    return Fill(
        intent=_intent(),
        filled_price=price,
        filled_quantity=quantity,
        filled_at=at,
        rejected=rejected,
        reject_reason=reject_reason,
        spread_cost_quote=spread,
        slippage_cost_quote=slippage,
        fee_cost_quote=fee,
        funding_cost_quote=funding,
    )


def test_client_order_id_is_deterministic() -> None:
    assert client_order_id_for("key-1") == client_order_id_for("key-1")
    assert client_order_id_for("key-1") != client_order_id_for("key-2")
    with pytest.raises(ValueError):
        client_order_id_for("  ")


def test_begin_order_is_idempotent(tmp_path: Path) -> None:
    store = PaperOrderStore(tmp_path / "orders.sqlite3")
    first = store.begin_order(
        idempotency_key="k1",
        symbol="BTCUSDT",
        side=IntentSide.BUY,
        quantity=1.0,
        reference_price=50_000.0,
        leg_group_id=None,
        now_utc=NOW,
    )
    second = store.begin_order(
        idempotency_key="k1",
        symbol="BTCUSDT",
        side=IntentSide.BUY,
        quantity=1.0,
        reference_price=50_000.0,
        leg_group_id=None,
        now_utc=NOW,
    )
    assert first.client_order_id == second.client_order_id
    assert first.state == PaperOrderState.PENDING_SUBMIT


def test_full_fill_lifecycle_updates_position(tmp_path: Path) -> None:
    store = PaperOrderStore(tmp_path / "orders.sqlite3")
    order = store.begin_order(
        idempotency_key="k1",
        symbol="BTCUSDT",
        side=IntentSide.BUY,
        quantity=1.0,
        reference_price=50_000.0,
        leg_group_id=None,
        now_utc=NOW,
    )
    store.mark_submitted(order.client_order_id, now_utc=NOW)
    result = store.apply_fill_result(
        order.client_order_id, _fill(quantity=1.0, price=50_010.0, fee=5.0)
    )
    assert result.state == PaperOrderState.FILLED
    assert result.filled_quantity == 1.0
    assert result.average_fill_price == 50_010.0
    assert result.fee_cost_quote == 5.0

    position = store.get_position("BTCUSDT")
    assert position is not None
    assert position.net_quantity == pytest.approx(1.0)
    assert position.average_price == pytest.approx(50_010.0)


def test_partial_fills_accumulate_to_a_weighted_average_price(tmp_path: Path) -> None:
    store = PaperOrderStore(tmp_path / "orders.sqlite3")
    order = store.begin_order(
        idempotency_key="k1",
        symbol="BTCUSDT",
        side=IntentSide.BUY,
        quantity=2.0,
        reference_price=50_000.0,
        leg_group_id=None,
        now_utc=NOW,
    )
    store.mark_submitted(order.client_order_id, now_utc=NOW)
    first = store.apply_fill_result(
        order.client_order_id, _fill(quantity=1.0, price=50_000.0, fee=1.0)
    )
    assert first.state == PaperOrderState.PARTIALLY_FILLED
    second = store.apply_fill_result(
        order.client_order_id, _fill(quantity=1.0, price=50_100.0, fee=1.0)
    )
    assert second.state == PaperOrderState.FILLED
    assert second.filled_quantity == pytest.approx(2.0)
    assert second.average_fill_price == pytest.approx(50_050.0)
    assert second.fee_cost_quote == pytest.approx(2.0)


def test_overfill_is_rejected(tmp_path: Path) -> None:
    store = PaperOrderStore(tmp_path / "orders.sqlite3")
    order = store.begin_order(
        idempotency_key="k1",
        symbol="BTCUSDT",
        side=IntentSide.BUY,
        quantity=1.0,
        reference_price=50_000.0,
        leg_group_id=None,
        now_utc=NOW,
    )
    store.mark_submitted(order.client_order_id, now_utc=NOW)
    with pytest.raises(PaperReconciliationError, match="overfilled"):
        store.apply_fill_result(order.client_order_id, _fill(quantity=1.5, price=50_000.0))


def test_rejection_path(tmp_path: Path) -> None:
    store = PaperOrderStore(tmp_path / "orders.sqlite3")
    order = store.begin_order(
        idempotency_key="k1",
        symbol="BTCUSDT",
        side=IntentSide.BUY,
        quantity=1.0,
        reference_price=50_000.0,
        leg_group_id=None,
        now_utc=NOW,
    )
    store.mark_submitted(order.client_order_id, now_utc=NOW)
    result = store.apply_fill_result(
        order.client_order_id,
        _fill(quantity=0.0, price=0.0, rejected=True, reject_reason="no liquidity"),
    )
    assert result.state == PaperOrderState.REJECTED
    assert result.reject_reason == "no liquidity"
    assert store.get_position("BTCUSDT") is None


def test_illegal_transitions_are_rejected(tmp_path: Path) -> None:
    store = PaperOrderStore(tmp_path / "orders.sqlite3")
    order = store.begin_order(
        idempotency_key="k1",
        symbol="BTCUSDT",
        side=IntentSide.BUY,
        quantity=1.0,
        reference_price=50_000.0,
        leg_group_id=None,
        now_utc=NOW,
    )
    with pytest.raises(PaperReconciliationError, match="cannot fill"):
        store.apply_fill_result(order.client_order_id, _fill(quantity=1.0, price=50_000.0))

    store.mark_submitted(order.client_order_id, now_utc=NOW)
    store.apply_fill_result(order.client_order_id, _fill(quantity=1.0, price=50_000.0))
    with pytest.raises(PaperReconciliationError, match="cannot submit"):
        store.mark_submitted(order.client_order_id, now_utc=NOW)
    with pytest.raises(PaperReconciliationError, match="cannot fill"):
        store.apply_fill_result(order.client_order_id, _fill(quantity=0.1, price=50_000.0))

    with pytest.raises(PaperReconciliationError, match="unknown"):
        store.mark_submitted("nonexistent", now_utc=NOW)


def test_ambiguous_order_survives_restart_and_is_listed(tmp_path: Path) -> None:
    path = tmp_path / "orders.sqlite3"
    store = PaperOrderStore(path)
    order = store.begin_order(
        idempotency_key="k1",
        symbol="BTCUSDT",
        side=IntentSide.BUY,
        quantity=1.0,
        reference_price=50_000.0,
        leg_group_id=None,
        now_utc=NOW,
    )
    store.mark_submitted(order.client_order_id, now_utc=NOW)
    # process "crashes" here, before an outcome is ever recorded

    reopened = PaperOrderStore(path)
    ambiguous = reopened.list_in_state(PaperOrderState.SUBMITTED)
    assert len(ambiguous) == 1
    assert ambiguous[0].client_order_id == order.client_order_id

    # the caller re-derives the same client_order_id from the same
    # idempotency key rather than risking a duplicate submission
    retried = reopened.begin_order(
        idempotency_key="k1",
        symbol="BTCUSDT",
        side=IntentSide.BUY,
        quantity=1.0,
        reference_price=50_000.0,
        leg_group_id=None,
        now_utc=NOW + timedelta(seconds=5),
    )
    assert retried.client_order_id == order.client_order_id
    assert retried.state == PaperOrderState.SUBMITTED


def test_reconcile_ambiguous_orders_resolves_or_leaves_unknown(tmp_path: Path) -> None:
    store = PaperOrderStore(tmp_path / "orders.sqlite3")
    known = store.begin_order(
        idempotency_key="known",
        symbol="BTCUSDT",
        side=IntentSide.BUY,
        quantity=1.0,
        reference_price=50_000.0,
        leg_group_id=None,
        now_utc=NOW,
    )
    unknown = store.begin_order(
        idempotency_key="unknown",
        symbol="ETHUSDT",
        side=IntentSide.BUY,
        quantity=1.0,
        reference_price=3_000.0,
        leg_group_id=None,
        now_utc=NOW,
    )
    store.mark_submitted(known.client_order_id, now_utc=NOW)
    store.mark_submitted(unknown.client_order_id, now_utc=NOW)

    def query_fn(client_order_id: str) -> Fill | None:
        if client_order_id == known.client_order_id:
            return _fill(quantity=1.0, price=50_005.0)
        return None

    resolved = store.reconcile_ambiguous_orders(query_fn)
    by_id = {record.client_order_id: record for record in resolved}
    assert by_id[known.client_order_id].state == PaperOrderState.FILLED
    assert by_id[unknown.client_order_id].state == PaperOrderState.SUBMITTED
    assert store.list_in_state(PaperOrderState.SUBMITTED) == (
        store.get(unknown.client_order_id),
    )


def test_leg_group_status_settled_rejected_and_orphaned(tmp_path: Path) -> None:
    store = PaperOrderStore(tmp_path / "orders.sqlite3")

    def _leg(key: str, group: str, symbol: str) -> str:
        order = store.begin_order(
            idempotency_key=key,
            symbol=symbol,
            side=IntentSide.BUY,
            quantity=1.0,
            reference_price=100.0,
            leg_group_id=group,
            now_utc=NOW,
        )
        store.mark_submitted(order.client_order_id, now_utc=NOW)
        return order.client_order_id

    settled_a = _leg("settled-a", "settled-group", "AAA")
    settled_b = _leg("settled-b", "settled-group", "BBB")
    store.apply_fill_result(settled_a, _fill(quantity=1.0, price=100.0))
    store.apply_fill_result(settled_b, _fill(quantity=1.0, price=100.0))
    assert store.leg_group_status("settled-group") == LegGroupStatus.SETTLED

    rejected_a = _leg("rejected-a", "rejected-group", "AAA")
    rejected_b = _leg("rejected-b", "rejected-group", "BBB")
    store.apply_fill_result(rejected_a, _fill(quantity=0, price=0, rejected=True))
    store.apply_fill_result(rejected_b, _fill(quantity=0, price=0, rejected=True))
    assert store.leg_group_status("rejected-group") == LegGroupStatus.CLEANLY_REJECTED

    orphan_a = _leg("orphan-a", "orphan-group", "AAA")
    orphan_b = _leg("orphan-b", "orphan-group", "BBB")
    store.apply_fill_result(orphan_a, _fill(quantity=1.0, price=100.0))
    store.apply_fill_result(orphan_b, _fill(quantity=0, price=0, rejected=True))
    assert store.leg_group_status("orphan-group") == LegGroupStatus.ORPHANED

    pending_group = "pending-group"
    _leg("pending-a", pending_group, "AAA")
    assert store.leg_group_status(pending_group) == LegGroupStatus.PENDING

    with pytest.raises(PaperReconciliationError, match="unknown paper leg group"):
        store.leg_group_status("does-not-exist")


def test_position_accounting_add_reduce_close_and_flip(tmp_path: Path) -> None:
    store = PaperOrderStore(tmp_path / "orders.sqlite3")

    def _fill_order(quantity: float, side: IntentSide, price: float, key: str) -> None:
        order = store.begin_order(
            idempotency_key=key,
            symbol="BTCUSDT",
            side=side,
            quantity=quantity,
            reference_price=price,
            leg_group_id=None,
            now_utc=NOW,
        )
        store.mark_submitted(order.client_order_id, now_utc=NOW)
        store.apply_fill_result(order.client_order_id, _fill(quantity=quantity, price=price))

    _fill_order(1.0, IntentSide.BUY, 100.0, "open")
    position = store.get_position("BTCUSDT")
    assert position is not None
    assert position.net_quantity == pytest.approx(1.0)
    assert position.average_price == pytest.approx(100.0)

    _fill_order(1.0, IntentSide.BUY, 200.0, "add")
    position = store.get_position("BTCUSDT")
    assert position is not None
    assert position.net_quantity == pytest.approx(2.0)
    assert position.average_price == pytest.approx(150.0)

    _fill_order(0.5, IntentSide.SELL, 250.0, "partial-close")
    position = store.get_position("BTCUSDT")
    assert position is not None
    assert position.net_quantity == pytest.approx(1.5)
    assert position.average_price == pytest.approx(150.0)
    assert position.realized_pnl_quote == pytest.approx(0.5 * (250.0 - 150.0))

    _fill_order(1.5, IntentSide.SELL, 150.0, "full-close")
    position = store.get_position("BTCUSDT")
    assert position is not None
    assert position.net_quantity == pytest.approx(0.0)
    realized_after_full_close = position.realized_pnl_quote

    _fill_order(1.0, IntentSide.SELL, 100.0, "flip-short")
    position = store.get_position("BTCUSDT")
    assert position is not None
    assert position.net_quantity == pytest.approx(-1.0)
    assert position.average_price == pytest.approx(100.0)
    assert position.realized_pnl_quote == pytest.approx(realized_after_full_close)


def test_fee_costs_accumulate_across_partial_fills_and_survive_restart(tmp_path: Path) -> None:
    path = tmp_path / "orders.sqlite3"
    store = PaperOrderStore(path)
    order = store.begin_order(
        idempotency_key="k1",
        symbol="BTCUSDT",
        side=IntentSide.BUY,
        quantity=2.0,
        reference_price=100.0,
        leg_group_id=None,
        now_utc=NOW,
    )
    store.mark_submitted(order.client_order_id, now_utc=NOW)
    store.apply_fill_result(
        order.client_order_id,
        _fill(quantity=1.0, price=100.0, spread=0.1, slippage=0.2, fee=0.3, funding=0.4),
    )

    # simulate a restart in the middle of a partial-fill sequence
    reopened = PaperOrderStore(path)
    reopened.apply_fill_result(
        order.client_order_id,
        _fill(quantity=1.0, price=100.0, spread=0.1, slippage=0.2, fee=0.3, funding=0.4),
    )
    final = reopened.get(order.client_order_id)
    assert final is not None
    assert final.state == PaperOrderState.FILLED
    assert final.spread_cost_quote == pytest.approx(0.2)
    assert final.slippage_cost_quote == pytest.approx(0.4)
    assert final.fee_cost_quote == pytest.approx(0.6)
    assert final.funding_cost_quote == pytest.approx(0.8)
