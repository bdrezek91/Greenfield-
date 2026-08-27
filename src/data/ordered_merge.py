"""Bounded-memory, connection-aware k-way merge for per-part event streams.

Sorting manifests by `min_receive_ts_ns` and concatenating each part's
already-locally-ordered rows (the pattern previously used by
`src.data.raw_store.iter_raw_events` and
`src.features.materialization`'s Gold builder) breaks down the moment two
parts' receive-time ranges genuinely overlap - which happens at every raw
collector reconnect. A fresh `connection_id` resets that connection's
process-local `receive_sequence` counter to zero (see
`BybitRawCollector.__init__`), and the old connection's final flush can
complete slightly after the new connection's first flush. Two parts from
*different* connections can then have overlapping
`[min_receive_ts_ns, max_receive_ts_ns]` ranges even though each part's own
rows - and each connection's own rows across all of its parts - remain
strictly ordered. Concatenating min-sorted parts in that case can emit a
row from the "later" part before a still-unconsumed, chronologically
earlier row from the "earlier" part: a real, reproducible cross-session
ordering violation, not random corruption and not something a caller
should route around by only ever processing single-connection windows.

The fix is a genuine streaming k-way merge over *sources* (parts), not a
"bucket everything by connection, then merge" two-phase algorithm - an
earlier version of this module did exactly that (`buckets.setdefault(...)
.append(row)` for the entire input before yielding anything), which made
memory grow with total row count instead of staying bounded. A real merge
over locally-sorted runs already produces a globally nondecreasing output
regardless of *why* the runs overlap; connection identity is only needed
to decide which regressions are genuine corruption (checked lazily, at the
moment each row is first read from its own source, against one remembered
key per connection - never by materializing a connection's full row set).

Each source also carries a `lower_bound` - a value from its manifest,
never from reading the part itself - so the merge can practice admission
control: a source is only opened (acquiring whatever file handle its
`open()` implies) once it is proven that no still-unopened source could
produce a smaller row. This bounds both the number of rows and the number
of concurrently open sources held in memory to however many are genuinely
"in flight" at once (typically just the sources spanning one reconnect),
never to the total number of sources or rows in the stream.
"""

from __future__ import annotations

import heapq
from collections.abc import Callable, Iterable, Iterator
from dataclasses import dataclass
from typing import Any, Generic, TypeVar

T = TypeVar("T")

OrderKey = tuple[Any, ...]
"""Any tuple of mutually-comparable, same-typed-per-position values - e.g.
`(receive_ts_ns, receive_sequence, event_id)` for raw events, or
`(receive_ts_ns, receive_sequence, row_index, normalized_id)` for
normalized rows that fan out multiple rows per raw event."""


class OrderedMergeError(RuntimeError):
    """One connection's own row stream is not strictly ordered."""


@dataclass(frozen=True, slots=True)
class MergeSource(Generic[T]):
    """One lazily-openable, already row-locally-ordered input to the merge.

    `lower_bound` must be `<=` the first element of `order_key(row)` for
    every row this source can produce (e.g. a part manifest's
    `min_receive_ts_ns`) - it lets the merge prove a source is safe to
    leave unopened without reading it. `open` is called at most once, only
    once admission control decides this source might hold the
    next-smallest outstanding row, and should return an iterator that
    itself streams rows (e.g. from a chunked Parquet reader) rather than
    materializing them all up front.
    """

    lower_bound: Any
    open: Callable[[], Iterator[T]]


def merge_rows_by_connection(
    sources: Iterable[MergeSource[T]],
    *,
    connection_id: Callable[[T], str],
    order_key: Callable[[T], OrderKey],
) -> Iterator[T]:
    """Stream a globally causal, connection-safe merge with bounded memory.

    `sources` must be supplied in ascending `lower_bound` order (e.g. parts
    sorted by their manifest's `min_receive_ts_ns`), and each source's own
    rows must already be ordered by `order_key`. Memory is bounded by the
    number of sources concurrently "in flight" (admitted but not yet
    exhausted) plus one remembered key per distinct `connection_id` ever
    seen - never by total row count or total source count. A source is
    opened only once admission control proves it might hold the
    next-smallest outstanding row, and is dropped the instant it is
    exhausted.

    Raises `OrderedMergeError` the moment a single connection's own rows
    regress or duplicate - a genuine data problem, never bypassed here.

    The check is applied at *ingestion* time (the instant a row is first
    pulled from its own source's iterator - at admission or at heap
    refill), never at emission (heap-pop) time. Those differ: admission
    control can legitimately open a later-sorting source before an
    earlier one is drained (that is exactly what makes a genuine
    reconnect overlap mergeable at all), so a single connection's rows can
    be *emitted* interleaved with a still-open source's rows without that
    being corruption. But a connection's own rows, in the order its own
    source(s) actually produce them, must always be non-decreasing -
    checking at ingestion time reproduces that per-source-local guarantee
    exactly, while checking at emission time would miss real corruption
    whenever a later-admitted part's row also happens to sort earliest
    globally.
    """
    pending = iter(sources)
    heap: list[tuple[OrderKey, int, T]] = []
    iterators: dict[int, Iterator[T]] = {}
    last_key_by_connection: dict[str, OrderKey] = {}
    next_index = 0

    def _ingest(row: T) -> OrderKey:
        conn = connection_id(row)
        key = order_key(row)
        previous = last_key_by_connection.get(conn)
        if previous is not None and key <= previous:
            raise OrderedMergeError(
                f"connection {conn!r} row order regressed or duplicated: "
                f"previous={previous}, observed={key}"
            )
        last_key_by_connection[conn] = key
        return key

    def _peek_pending() -> MergeSource[T] | None:
        return next(pending, None)

    next_pending = _peek_pending()

    while True:
        while next_pending is not None and (
            not heap or next_pending.lower_bound <= heap[0][0][0]
        ):
            source = next_pending
            it = source.open()
            first = next(it, None)
            if first is not None:
                key = _ingest(first)
                iterators[next_index] = it
                heapq.heappush(heap, (key, next_index, first))
            next_index += 1
            next_pending = _peek_pending()

        if not heap:
            return

        _, idx, row = heapq.heappop(heap)
        yield row

        it = iterators[idx]
        nxt = next(it, None)
        if nxt is not None:
            nxt_key = _ingest(nxt)
            heapq.heappush(heap, (nxt_key, idx, nxt))
        else:
            del iterators[idx]
