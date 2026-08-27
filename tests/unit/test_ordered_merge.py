"""merge_rows_by_connection reproduces the real cross-session ordering bug
in isolation, and proves the fix without any Bybit-specific plumbing.
"""

from __future__ import annotations

from dataclasses import dataclass

import pytest

from src.data.ordered_merge import OrderedMergeError, merge_rows_by_connection


@dataclass(frozen=True, slots=True)
class Row:
    connection_id: str
    receive_ts_ns: int
    receive_sequence: int
    row_id: str


def _order_key(row: Row) -> tuple[int, int, str]:
    return (row.receive_ts_ns, row.receive_sequence, row.row_id)


def test_overlapping_connections_merge_into_global_order() -> None:
    # Reproduces the real observed failure shape: connection "old" is still
    # flushing its tail (receive_sequence 293-295) while connection "new"
    # has already started (receive_sequence 1-3), and "new"'s first events
    # land at an EARLIER receive_ts_ns than "old"'s last ones - exactly the
    # phase1-20260825t164500z -> phase1-20260825t164933z restart shape.
    old_tail = [
        Row("old", 1787676323_000_000_000, 293, "old-293"),
        Row("old", 1787676323_500_000_000, 294, "old-294"),
        Row("old", 1787676327_236_331_717, 295, "old-295"),
    ]
    new_head = [
        Row("new", 1787676323_166_283_259, 1, "new-1"),
        Row("new", 1787676323_400_000_000, 2, "new-2"),
        Row("new", 1787676330_000_000_000, 3, "new-3"),
    ]
    # Manifest-order (min_receive_ts_ns ascending): "old" part sorts first
    # (min 1787676323_000_000_000), "new" part sorts second (min
    # 1787676323_166_283_259) - the exact ordering that broke the old
    # concatenate-after-sort approach, since old's own range extends past
    # new's start.
    parts = [old_tail, new_head]

    merged = list(
        merge_rows_by_connection(parts, connection_id=lambda r: r.connection_id, order_key=_order_key)
    )

    assert [row.row_id for row in merged] == [
        "old-293",
        "new-1",
        "new-2",
        "old-294",
        "old-295",
        "new-3",
    ]
    # The merged stream is globally sorted by receive_ts_ns - the property
    # a naive concatenate-after-manifest-sort could not guarantee.
    timestamps = [row.receive_ts_ns for row in merged]
    assert timestamps == sorted(timestamps)


def test_no_events_lost_or_duplicated() -> None:
    old = [Row("old", ts, i, f"old-{i}") for i, ts in enumerate((100, 200, 300), start=1)]
    new = [Row("new", ts, i, f"new-{i}") for i, ts in enumerate((150, 250, 350), start=1)]

    merged = list(
        merge_rows_by_connection([old, new], connection_id=lambda r: r.connection_id, order_key=_order_key)
    )

    assert {row.row_id for row in merged} == {row.row_id for row in old + new}
    assert len(merged) == len(old) + len(new)


def test_single_connection_regression_still_fails_closed() -> None:
    # A genuine intra-connection regression (real corruption, not a
    # reconnect artifact) must still raise - the fix narrows the check to
    # be connection-scoped, it does not weaken it.
    rows = [
        Row("only", 100, 1, "a"),
        Row("only", 90, 2, "b"),  # regressed receive_ts_ns within the SAME connection
    ]

    with pytest.raises(OrderedMergeError, match="only"):
        list(merge_rows_by_connection([rows], connection_id=lambda r: r.connection_id, order_key=_order_key))


def test_single_connection_duplicate_still_fails_closed() -> None:
    rows = [
        Row("only", 100, 1, "a"),
        Row("only", 100, 1, "a"),  # exact duplicate
    ]

    with pytest.raises(OrderedMergeError):
        list(merge_rows_by_connection([rows], connection_id=lambda r: r.connection_id, order_key=_order_key))


def test_empty_input_yields_nothing() -> None:
    assert list(merge_rows_by_connection([], connection_id=lambda r: r.connection_id, order_key=_order_key)) == []


def test_three_way_overlap_stays_globally_sorted() -> None:
    a = [Row("a", ts, i, f"a-{i}") for i, ts in enumerate((10, 40, 70), start=1)]
    b = [Row("b", ts, i, f"b-{i}") for i, ts in enumerate((20, 50, 80), start=1)]
    c = [Row("c", ts, i, f"c-{i}") for i, ts in enumerate((30, 60, 90), start=1)]

    merged = list(
        merge_rows_by_connection([a, b, c], connection_id=lambda r: r.connection_id, order_key=_order_key)
    )
    timestamps = [row.receive_ts_ns for row in merged]
    assert timestamps == sorted(timestamps)
    assert len(merged) == 9
