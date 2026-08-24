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
    fill_id: str = "",
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
        fill_id=fill_id,
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
        order.client_order_id, _fill(quantity=1.0, price=50_010.0, fee=5.0, fill_id="fill-1")
    )
    assert result.state == PaperOrderState.FILLED
    assert result.filled_quantity == 1.0
    assert result.average_fill_price == 50_010.0
    assert result.fee_cost_quote == 5.0

    position = store.get_position("BTCUSDT")
    assert position is not None
    assert position.net_quantity == pytest.approx(1.0)
    assert position.average_price == pytest.approx(50_010.0)


def test_cancel_is_terminal_idempotent_and_preserves_partial_fill(tmp_path: Path) -> None:
    store = PaperOrderStore(tmp_path / "orders.sqlite3")
    order = store.begin_order(
        idempotency_key="cancel-1",
        symbol="BTCUSDT",
        side=IntentSide.BUY,
        quantity=1.0,
        reference_price=50_000.0,
        leg_group_id="cancel-group",
        now_utc=NOW,
    )
    store.mark_submitted(order.client_order_id, now_utc=NOW)
    store.apply_fill_result(
        order.client_order_id,
        _fill(quantity=0.25, price=50_010.0, fill_id="cancel-fill-1"),
    )

    canceled = store.mark_canceled(
        order.client_order_id, now_utc=NOW + timedelta(seconds=1)
    )
    replayed = store.mark_canceled(
        order.client_order_id, now_utc=NOW + timedelta(seconds=2)
    )

    assert canceled.state is PaperOrderState.CANCELED
    assert canceled.filled_quantity == pytest.approx(0.25)
    assert replayed == canceled
    assert store.leg_group_status("cancel-group") is LegGroupStatus.ORPHANED
    position = store.get_position("BTCUSDT")
    assert position is not None and position.net_quantity == pytest.approx(0.25)
    with pytest.raises(PaperReconciliationError, match="cannot fill"):
        store.apply_fill_result(
            order.client_order_id,
            _fill(quantity=0.25, price=50_020.0, fill_id="late-after-cancel"),
        )


def test_zero_fill_canceled_leg_group_is_cleanly_terminal(tmp_path: Path) -> None:
    store = PaperOrderStore(tmp_path / "orders.sqlite3")
    order = store.begin_order(
        idempotency_key="cancel-zero",
        symbol="BTCUSDT",
        side=IntentSide.BUY,
        quantity=1.0,
        reference_price=50_000.0,
        leg_group_id="cancel-zero-group",
        now_utc=NOW,
    )
    store.mark_submitted(order.client_order_id, now_utc=NOW)
    store.mark_canceled(order.client_order_id, now_utc=NOW + timedelta(seconds=1))

    assert store.leg_group_status("cancel-zero-group") is LegGroupStatus.CLEANLY_REJECTED


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
        order.client_order_id, _fill(quantity=1.0, price=50_000.0, fee=1.0, fill_id="fill-1")
    )
    assert first.state == PaperOrderState.PARTIALLY_FILLED
    second = store.apply_fill_result(
        order.client_order_id, _fill(quantity=1.0, price=50_100.0, fee=1.0, fill_id="fill-2")
    )
    assert second.state == PaperOrderState.FILLED
    assert second.filled_quantity == pytest.approx(2.0)
    assert second.average_fill_price == pytest.approx(50_050.0)
    assert second.fee_cost_quote == pytest.approx(2.0)

    fills = store.list_fills(order.client_order_id)
    assert {f.fill_id for f in fills} == {"fill-1", "fill-2"}


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
        store.apply_fill_result(
            order.client_order_id, _fill(quantity=1.5, price=50_000.0, fill_id="fill-1")
        )


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
        store.apply_fill_result(
            order.client_order_id, _fill(quantity=1.0, price=50_000.0, fill_id="fill-1")
        )

    store.mark_submitted(order.client_order_id, now_utc=NOW)
    store.apply_fill_result(
        order.client_order_id, _fill(quantity=1.0, price=50_000.0, fill_id="fill-1")
    )
    with pytest.raises(PaperReconciliationError, match="cannot submit"):
        store.mark_submitted(order.client_order_id, now_utc=NOW)
    with pytest.raises(PaperReconciliationError, match="cannot fill"):
        store.apply_fill_result(
            order.client_order_id, _fill(quantity=0.1, price=50_000.0, fill_id="fill-2")
        )

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
            return _fill(quantity=1.0, price=50_005.0, fill_id="exchange-fill-1")
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
    store.apply_fill_result(settled_a, _fill(quantity=1.0, price=100.0, fill_id="settled-a-fill"))
    store.apply_fill_result(settled_b, _fill(quantity=1.0, price=100.0, fill_id="settled-b-fill"))
    assert store.leg_group_status("settled-group") == LegGroupStatus.SETTLED

    rejected_a = _leg("rejected-a", "rejected-group", "AAA")
    rejected_b = _leg("rejected-b", "rejected-group", "BBB")
    store.apply_fill_result(rejected_a, _fill(quantity=0, price=0, rejected=True))
    store.apply_fill_result(rejected_b, _fill(quantity=0, price=0, rejected=True))
    assert store.leg_group_status("rejected-group") == LegGroupStatus.CLEANLY_REJECTED

    orphan_a = _leg("orphan-a", "orphan-group", "AAA")
    orphan_b = _leg("orphan-b", "orphan-group", "BBB")
    store.apply_fill_result(orphan_a, _fill(quantity=1.0, price=100.0, fill_id="orphan-a-fill"))
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
        store.apply_fill_result(
            order.client_order_id, _fill(quantity=quantity, price=price, fill_id=f"{key}-fill")
        )

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
        _fill(
            quantity=1.0,
            price=100.0,
            spread=0.1,
            slippage=0.2,
            fee=0.3,
            funding=0.4,
            fill_id="fill-1",
        ),
    )

    # simulate a restart in the middle of a partial-fill sequence; this is a
    # second, distinct fill (its own fill_id) that happens to carry the same
    # notional values as the first - not a redelivery of it
    reopened = PaperOrderStore(path)
    reopened.apply_fill_result(
        order.client_order_id,
        _fill(
            quantity=1.0,
            price=100.0,
            spread=0.1,
            slippage=0.2,
            fee=0.3,
            funding=0.4,
            fill_id="fill-2",
        ),
    )
    final = reopened.get(order.client_order_id)
    assert final is not None
    assert final.state == PaperOrderState.FILLED
    assert final.spread_cost_quote == pytest.approx(0.2)
    assert final.slippage_cost_quote == pytest.approx(0.4)
    assert final.fee_cost_quote == pytest.approx(0.6)
    assert final.funding_cost_quote == pytest.approx(0.8)
    assert len(reopened.list_fills(order.client_order_id)) == 2


def test_identical_fill_redelivered_after_restart_is_not_double_applied(tmp_path: Path) -> None:
    """The producer commits a fill, the process crashes before it learns that,
    and on restart it redelivers the exact same fill (same fill_id, same
    content). The store must recognize the replay and refuse to double-count
    filled_quantity, costs, or position - not raise, not duplicate.
    """
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
    first_fill = _fill(quantity=1.0, price=50_010.0, fee=5.0, fill_id="exec-1")
    first_result = store.apply_fill_result(order.client_order_id, first_fill)
    assert first_result.state == PaperOrderState.FILLED

    # process "crashes" and restarts here, then the same fill is redelivered
    reopened = PaperOrderStore(path)
    replayed_result = reopened.apply_fill_result(order.client_order_id, first_fill)

    assert replayed_result.filled_quantity == pytest.approx(1.0)
    assert replayed_result.state == PaperOrderState.FILLED
    assert replayed_result.fee_cost_quote == pytest.approx(5.0)
    assert len(reopened.list_fills(order.client_order_id)) == 1

    position = reopened.get_position("BTCUSDT")
    assert position is not None
    assert position.net_quantity == pytest.approx(1.0)


def test_fill_id_reused_with_different_content_is_rejected(tmp_path: Path) -> None:
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
    store.apply_fill_result(
        order.client_order_id, _fill(quantity=1.0, price=50_000.0, fill_id="exec-1")
    )

    with pytest.raises(PaperReconciliationError, match="exec-1"):
        store.apply_fill_result(
            order.client_order_id, _fill(quantity=1.0, price=51_000.0, fill_id="exec-1")
        )

    # the conflicting attempt must not have been applied
    unchanged = store.get(order.client_order_id)
    assert unchanged is not None
    assert unchanged.filled_quantity == pytest.approx(1.0)
    assert unchanged.state == PaperOrderState.PARTIALLY_FILLED


def test_fill_id_reused_across_different_orders_is_rejected(tmp_path: Path) -> None:
    store = PaperOrderStore(tmp_path / "orders.sqlite3")
    first_order = store.begin_order(
        idempotency_key="k1",
        symbol="BTCUSDT",
        side=IntentSide.BUY,
        quantity=1.0,
        reference_price=50_000.0,
        leg_group_id=None,
        now_utc=NOW,
    )
    second_order = store.begin_order(
        idempotency_key="k2",
        symbol="ETHUSDT",
        side=IntentSide.BUY,
        quantity=1.0,
        reference_price=3_000.0,
        leg_group_id=None,
        now_utc=NOW,
    )
    store.mark_submitted(first_order.client_order_id, now_utc=NOW)
    store.mark_submitted(second_order.client_order_id, now_utc=NOW)
    store.apply_fill_result(
        first_order.client_order_id, _fill(quantity=1.0, price=50_000.0, fill_id="shared-id")
    )

    with pytest.raises(PaperReconciliationError, match="shared-id"):
        store.apply_fill_result(
            second_order.client_order_id, _fill(quantity=1.0, price=3_000.0, fill_id="shared-id")
        )


def test_fill_without_fill_id_is_refused(tmp_path: Path) -> None:
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
    with pytest.raises(ValueError, match="fill_id"):
        store.apply_fill_result(order.client_order_id, _fill(quantity=1.0, price=50_000.0))


def test_begin_order_identical_retry_after_restart_is_idempotent(tmp_path: Path) -> None:
    path = tmp_path / "orders.sqlite3"
    store = PaperOrderStore(path)
    first = store.begin_order(
        idempotency_key="k1",
        symbol="BTCUSDT",
        side=IntentSide.BUY,
        quantity=1.0,
        reference_price=50_000.0,
        leg_group_id="group-1",
        now_utc=NOW,
    )

    reopened = PaperOrderStore(path)
    retried = reopened.begin_order(
        idempotency_key="k1",
        symbol="BTCUSDT",
        side=IntentSide.BUY,
        quantity=1.0,
        reference_price=50_000.0,
        leg_group_id="group-1",
        now_utc=NOW + timedelta(seconds=5),
    )
    assert retried.client_order_id == first.client_order_id
    assert retried.created_at_utc == first.created_at_utc


@pytest.mark.parametrize(
    "overrides",
    [
        {"symbol": "ETHUSDT"},
        {"side": IntentSide.SELL},
        {"quantity": 2.0},
        {"reference_price": 51_000.0},
        {"leg_group_id": "different-group"},
    ],
)
def test_begin_order_idempotency_key_conflict_is_rejected(
    tmp_path: Path, overrides: dict[str, object]
) -> None:
    store = PaperOrderStore(tmp_path / "orders.sqlite3")
    base_params: dict[str, object] = {
        "idempotency_key": "k1",
        "symbol": "BTCUSDT",
        "side": IntentSide.BUY,
        "quantity": 1.0,
        "reference_price": 50_000.0,
        "leg_group_id": None,
        "now_utc": NOW,
    }
    store.begin_order(**base_params)  # type: ignore[arg-type]

    conflicting_params = dict(base_params) | overrides
    with pytest.raises(PaperReconciliationError, match="idempotency_key"):
        store.begin_order(**conflicting_params)  # type: ignore[arg-type]

    # the original order must be untouched by the rejected conflicting attempt
    unchanged = store.get_by_idempotency_key("k1")
    assert unchanged is not None
    assert unchanged.symbol == "BTCUSDT"
    assert unchanged.quantity == pytest.approx(1.0)
