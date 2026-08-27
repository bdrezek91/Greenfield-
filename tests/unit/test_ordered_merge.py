"""merge_rows_by_connection reproduces the real cross-session ordering bug
in isolation, proves the fix without any Bybit-specific plumbing, and
proves the merge is genuinely bounded-memory (not "buckets everything by
connection first, then yields" - the earlier, broken version of this
module did exactly that).
"""

from __future__ import annotations

import tracemalloc
from dataclasses import dataclass

import pytest

from src.data.ordered_merge import MergeSource, OrderedMergeError, merge_rows_by_connection


@dataclass(frozen=True, slots=True)
class Row:
    connection_id: str
    receive_ts_ns: int
    receive_sequence: int
    row_id: str


def _order_key(row: Row) -> tuple[int, int, str]:
    return (row.receive_ts_ns, row.receive_sequence, row.row_id)


def _sources(parts: list[list[Row]]) -> list[MergeSource[Row]]:
    """Wrap plain in-memory lists as lazily-opened, admission-controlled sources."""
    return [
        MergeSource(
            lower_bound=min(row.receive_ts_ns for row in part),
            open=(lambda part=part: iter(part)),
        )
        for part in parts
        if part
    ]


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
        merge_rows_by_connection(
            _sources(parts), connection_id=lambda r: r.connection_id, order_key=_order_key
        )
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
        merge_rows_by_connection(
            _sources([old, new]), connection_id=lambda r: r.connection_id, order_key=_order_key
        )
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
        list(
            merge_rows_by_connection(
                _sources([rows]), connection_id=lambda r: r.connection_id, order_key=_order_key
            )
        )


def test_single_connection_duplicate_still_fails_closed() -> None:
    rows = [
        Row("only", 100, 1, "a"),
        Row("only", 100, 1, "a"),  # exact duplicate
    ]

    with pytest.raises(OrderedMergeError):
        list(
            merge_rows_by_connection(
                _sources([rows]), connection_id=lambda r: r.connection_id, order_key=_order_key
            )
        )


def test_empty_input_yields_nothing() -> None:
    assert (
        list(
            merge_rows_by_connection(
                [], connection_id=lambda r: r.connection_id, order_key=_order_key
            )
        )
        == []
    )


def test_three_way_overlap_stays_globally_sorted() -> None:
    a = [Row("a", ts, i, f"a-{i}") for i, ts in enumerate((10, 40, 70), start=1)]
    b = [Row("b", ts, i, f"b-{i}") for i, ts in enumerate((20, 50, 80), start=1)]
    c = [Row("c", ts, i, f"c-{i}") for i, ts in enumerate((30, 60, 90), start=1)]

    merged = list(
        merge_rows_by_connection(
            _sources([a, b, c]), connection_id=lambda r: r.connection_id, order_key=_order_key
        )
    )
    timestamps = [row.receive_ts_ns for row in merged]
    assert timestamps == sorted(timestamps)
    assert len(merged) == 9


def test_sources_out_of_lower_bound_order_still_merge_correctly() -> None:
    """Regression test for a real bug found validating this fix against
    production data: a caller (materialization._build_bounded_frames)
    passed sources sorted by a DIFFERENT field than the one used as
    `lower_bound`, silently breaking admission control's ordering
    guarantee and raising a spurious OrderedMergeError against
    uncorrupted data. The merge must not trust caller order - it sorts
    `sources` by `lower_bound` itself.
    """
    a = [Row("a", ts, i, f"a-{i}") for i, ts in enumerate((10, 40, 70), start=1)]
    b = [Row("b", ts, i, f"b-{i}") for i, ts in enumerate((20, 50, 80), start=1)]
    c = [Row("c", ts, i, f"c-{i}") for i, ts in enumerate((30, 60, 90), start=1)]

    sources_in_order = _sources([a, b, c])
    # Deliberately shuffled - NOT ascending by lower_bound (a=10, b=20, c=30).
    shuffled = [sources_in_order[2], sources_in_order[0], sources_in_order[1]]

    merged = list(
        merge_rows_by_connection(
            shuffled, connection_id=lambda r: r.connection_id, order_key=_order_key
        )
    )
    timestamps = [row.receive_ts_ns for row in merged]
    assert timestamps == sorted(timestamps)
    assert len(merged) == 9
    assert {row.row_id for row in merged} == {row.row_id for row in a + b + c}


def test_sources_are_not_opened_until_admitted() -> None:
    """The merge must not read a source before proving it might be needed.

    This is the direct regression test for the original bug: the previous
    implementation did `for part in parts: for row in part: ...` for the
    ENTIRE input before yielding a single row, which meant every source was
    opened immediately regardless of admission control.
    """
    opened: list[str] = []

    def _tracking_source(name: str, rows: list[Row]) -> MergeSource[Row]:
        def _open() -> "iter[Row]":
            opened.append(name)
            return iter(rows)

        return MergeSource(lower_bound=min(r.receive_ts_ns for r in rows), open=_open)

    # "late" starts at receive_ts_ns=10_000 - far past "early"'s single row
    # at receive_ts_ns=1. Nothing about "late" can be needed until the
    # merge has fully drained "early".
    early = [Row("early", 1, 1, "early-1")]
    late = [Row("late", 10_000, 1, "late-1")]
    sources = [
        _tracking_source("early", early),
        _tracking_source("late", late),
    ]

    merge = merge_rows_by_connection(
        sources, connection_id=lambda r: r.connection_id, order_key=_order_key
    )
    first_row = next(merge)
    assert first_row.row_id == "early-1"
    # "late" has a much larger lower_bound than "early"'s only row, so it
    # must not have been opened yet just to produce the first output row.
    assert opened == ["early"]

    remaining = list(merge)
    assert [row.row_id for row in remaining] == ["late-1"]
    assert opened == ["early", "late"]


def test_peak_memory_does_not_scale_with_total_row_count() -> None:
    """Bounded-memory invariant: peak memory for a merge over many small,
    lazily-opened parts must be dominated by the batch size in flight, not
    by the total number of rows across all parts.

    Each part is opened as a generator that yields rows one at a time
    rather than a pre-built list, so if the merge implementation still
    buffered whole parts (or the whole stream) into a dict/list before
    yielding - the original bug - peak traced memory would grow
    proportionally with `total_rows`. A genuinely streaming, admission-
    controlled merge instead peaks near a small constant multiple of
    `rows_per_part`.
    """

    def _lazy_part(connection: str, base_ts: int, count: int):
        def _rows():
            for i in range(count):
                yield Row(connection, base_ts + i, i, f"{connection}-{i}")

        return _rows

    num_parts = 200
    rows_per_part = 50
    total_rows = num_parts * rows_per_part

    sources = [
        MergeSource(
            lower_bound=part_index * rows_per_part,
            open=_lazy_part(f"conn-{part_index}", part_index * rows_per_part, rows_per_part),
        )
        for part_index in range(num_parts)
    ]

    tracemalloc.start()
    try:
        merged_count = 0
        peak_during_merge = 0
        merge = merge_rows_by_connection(
            sources,
            connection_id=lambda r: r.connection_id,
            order_key=_order_key,
            # Not the default (order_key): row_id strings like "conn-0-10"
            # sort lexicographically before "conn-0-9", which would trip
            # the component-wise regression check on an artifact of this
            # fixture's naming, not a real regression.
            connection_sequence_key=lambda r: (r.receive_ts_ns, r.receive_sequence),
        )
        for _ in merge:
            merged_count += 1
            if merged_count % 500 == 0:
                _, peak = tracemalloc.get_traced_memory()
                peak_during_merge = max(peak_during_merge, peak)
        _, final_peak = tracemalloc.get_traced_memory()
        peak_during_merge = max(peak_during_merge, final_peak)
    finally:
        tracemalloc.stop()

    assert merged_count == total_rows
    # Each Row is tiny; if the whole stream (or even one connection's full
    # bucket) were materialized, peak would scale with total_rows (10,000
    # rows here). A bounded merge should stay within a small constant
    # factor of one part's worth of rows. Generous but discriminating
    # bound: well under total_rows worth of Row objects.
    assert peak_during_merge < total_rows * 200, (
        f"peak traced memory {peak_during_merge} bytes suggests the merge is "
        f"materializing the whole stream instead of streaming it "
        f"(total_rows={total_rows})"
    )
