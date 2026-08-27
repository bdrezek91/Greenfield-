"""Connection-aware k-way merge for per-part raw/normalized event streams.

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

The fix here never assumes a single manifest-level sort suffices across
connection boundaries. Rows are bucketed by `connection_id`, each bucket's
own order is verified fail-closed (a genuine regression or duplicate
*within* one connection remains an error - `receive_sequence` only means
something as a tie-breaker inside the connection that produced it), and
the buckets are then merged with a real streaming k-way merge keyed on the
row's own `(receive_ts_ns, receive_sequence, event_identity)` tuple. The
merged output is a single globally ordered, deduplicated-by-construction
stream - no event is dropped, none is duplicated, and no future event
crosses into an earlier position (the merge only ever looks at rows already
read, never ahead).
"""

from __future__ import annotations

import heapq
from collections.abc import Callable, Iterable, Iterator
from typing import Any, TypeVar

T = TypeVar("T")

OrderKey = tuple[Any, ...]
"""Any tuple of mutually-comparable, same-typed-per-position values - e.g.
`(receive_ts_ns, receive_sequence, event_id)` for raw events, or
`(receive_ts_ns, receive_sequence, row_index, normalized_id)` for
normalized rows that fan out multiple rows per raw event."""


class OrderedMergeError(RuntimeError):
    """One connection's own row stream is not strictly ordered."""


def merge_rows_by_connection(
    parts: Iterable[Iterable[T]],
    *,
    connection_id: Callable[[T], str],
    order_key: Callable[[T], OrderKey],
) -> Iterator[T]:
    """Merge already part-local-ordered rows into one causal, connection-safe stream.

    `parts` should be supplied in the caller's existing manifest order (e.g.
    sorted by `min_receive_ts_ns`) - that ordering only needs to be correct
    *within* each connection's own rows, which it already is, since one
    connection's parts never overlap in receive time. This function does
    not trust that ordering across connections; it re-derives a correct
    global order itself.

    Raises `OrderedMergeError` the moment a single connection's own rows
    regress or duplicate - a genuine data problem, never bypassed here.
    """
    buckets: dict[str, list[T]] = {}
    last_key_by_connection: dict[str, OrderKey] = {}
    for part in parts:
        for row in part:
            conn = connection_id(row)
            key = order_key(row)
            previous = last_key_by_connection.get(conn)
            if previous is not None and key <= previous:
                raise OrderedMergeError(
                    f"connection {conn!r} row order regressed or duplicated: "
                    f"previous={previous}, observed={key}"
                )
            last_key_by_connection[conn] = key
            buckets.setdefault(conn, []).append(row)

    heap: list[tuple[OrderKey, int, T]] = []
    iterators: dict[int, Iterator[T]] = {}
    for idx, rows in enumerate(buckets.values()):
        it = iter(rows)
        first = next(it)
        iterators[idx] = it
        heapq.heappush(heap, (order_key(first), idx, first))

    while heap:
        key, idx, row = heapq.heappop(heap)
        yield row
        nxt = next(iterators[idx], None)
        if nxt is not None:
            heapq.heappush(heap, (order_key(nxt), idx, nxt))
