"""OrderBookState must apply snapshot/delta correctly and summarize
top-of-book imbalance.
"""

from __future__ import annotations

from src.data.orderbook_state import OrderBookState


def test_summary_is_none_before_any_snapshot() -> None:
    state = OrderBookState()
    assert state.summary() is None


def test_snapshot_populates_book_and_computes_summary() -> None:
    state = OrderBookState(top_n=10)
    state.apply_snapshot(
        bids=[["100.0", "1.0"], ["99.0", "2.0"]],
        asks=[["101.0", "1.0"], ["102.0", "1.0"]],
    )

    summary = state.summary()
    assert summary is not None
    assert summary.best_bid == 100.0
    assert summary.best_ask == 101.0
    assert summary.mid_price == 100.5
    assert summary.spread == 1.0
    assert summary.bid_qty_top == 3.0
    assert summary.ask_qty_top == 2.0
    assert summary.imbalance == (3.0 - 2.0) / (3.0 + 2.0)


def test_delta_upserts_a_level() -> None:
    state = OrderBookState()
    state.apply_snapshot(bids=[["100.0", "1.0"]], asks=[["101.0", "1.0"]])
    state.apply_delta(bids=[["100.0", "5.0"]], asks=[])

    assert state.summary().bid_qty_top == 5.0


def test_delta_with_zero_size_removes_a_level() -> None:
    state = OrderBookState()
    state.apply_snapshot(
        bids=[["100.0", "1.0"], ["99.0", "2.0"]], asks=[["101.0", "1.0"]]
    )
    state.apply_delta(bids=[["99.0", "0"]], asks=[])

    assert state.summary().best_bid == 100.0
    assert state.summary().bid_qty_top == 1.0


def test_a_second_snapshot_fully_replaces_the_book() -> None:
    state = OrderBookState()
    state.apply_snapshot(bids=[["100.0", "1.0"]], asks=[["101.0", "1.0"]])
    state.apply_snapshot(bids=[["50.0", "9.0"]], asks=[["51.0", "9.0"]])

    summary = state.summary()
    assert summary.best_bid == 50.0
    assert summary.best_ask == 51.0


def test_imbalance_is_zero_when_both_sides_empty_after_removal() -> None:
    state = OrderBookState()
    state.apply_snapshot(bids=[["100.0", "1.0"]], asks=[["101.0", "1.0"]])
    state.apply_delta(bids=[["100.0", "0"]], asks=[])
    # Bid side now empty - book is no longer "ready" (needs both sides).
    assert state.summary() is None


def test_top_n_limits_how_many_levels_are_summed() -> None:
    state = OrderBookState(top_n=1)
    state.apply_snapshot(
        bids=[["100.0", "1.0"], ["99.0", "100.0"]],
        asks=[["101.0", "1.0"], ["102.0", "100.0"]],
    )
    summary = state.summary()
    assert summary.bid_qty_top == 1.0  # only the best level (100.0), not 99.0's 100 qty
    assert summary.ask_qty_top == 1.0
