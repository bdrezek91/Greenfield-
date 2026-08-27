"""Subprocess worker for test_raw_replay_bounded_memory.py.

Writes a synthetic multi-connection, multi-part raw lake (with genuinely
overlapping receive-time ranges across connections, the real reconnect
shape) and fully drains `iter_raw_events` over it, then reports process
peak RSS delta attributable to that work - isolated from Python/pandas/
pyarrow import overhead by taking the baseline *after* imports, before any
data is written or read.

Run as: python _bounded_memory_replay_worker.py <data_dir> <connections>
<parts_per_connection> <rows_per_part>
"""

from __future__ import annotations

import json
import resource
import sys
from pathlib import Path

from src.data.raw_event import parse_bybit_message
from src.data.raw_store import AtomicRawWriter, iter_raw_events


def _peak_rss_kb() -> int:
    return resource.getrusage(resource.RUSAGE_SELF).ru_maxrss


def _event(*, receive_ts_ns: int, receive_sequence: int, connection_id: str, update_id: int):
    # ~300 byte payload, representative of a real Bybit L2 delta message -
    # large enough that fully materializing thousands of these at once is a
    # visible, discriminating memory cost.
    payload = (
        '{"topic":"orderbook.50.BTCUSDT","type":"delta","ts":1700000000000,'
        f'"data":{{"s":"BTCUSDT",'
        f'"b":[["100.1","1.5"],["100.0","2.5"],["99.9","0.75"],["99.8","3.25"]],'
        f'"a":[["100.2","1.1"],["100.3","2.2"],["100.4","0.5"],["100.5","4.0"]],'
        f'"u":{update_id},"seq":{update_id + 10}}}}}'
    )
    return parse_bybit_message(
        payload,
        receive_ts_ns=receive_ts_ns,
        connection_id=connection_id,
        receive_sequence=receive_sequence,
    )


def main() -> None:
    data_dir = Path(sys.argv[1])
    connections = int(sys.argv[2])
    parts_per_connection = int(sys.argv[3])
    rows_per_part = int(sys.argv[4])

    baseline_rss_kb = _peak_rss_kb()

    writer = AtomicRawWriter(data_dir)
    # Stagger each connection's start so adjacent connections' receive-time
    # ranges genuinely overlap - the real reconnect shape - instead of the
    # trivially easy case of disjoint, back-to-back ranges.
    connection_stride_ns = rows_per_part * 500_000  # 0.5ms per row, per part
    overlap_ns = connection_stride_ns // 3
    epoch_ns = 1_700_000_000_000_000_000  # realistic ns epoch, keeps every ts positive
    for conn_index in range(connections):
        connection_id = f"conn-{conn_index}"
        base_ts = epoch_ns + conn_index * (connection_stride_ns * parts_per_connection - overlap_ns)
        for part_index in range(parts_per_connection):
            part_base = base_ts + part_index * connection_stride_ns
            events = [
                _event(
                    receive_ts_ns=part_base + row_index * 500_000,
                    receive_sequence=part_index * rows_per_part + row_index + 1,
                    connection_id=connection_id,
                    update_id=part_index * rows_per_part + row_index + 1,
                )
                for row_index in range(rows_per_part)
            ]
            writer.write(events)

    row_count = 0
    for _ in iter_raw_events(data_dir, exchange="bybit", market_type="linear"):
        row_count += 1

    final_rss_kb = _peak_rss_kb()
    expected_total = connections * parts_per_connection * rows_per_part
    assert row_count == expected_total, f"expected {expected_total} rows, got {row_count}"

    print(
        json.dumps(
            {
                "row_count": row_count,
                "baseline_rss_kb": baseline_rss_kb,
                "final_rss_kb": final_rss_kb,
                "delta_rss_kb": final_rss_kb - baseline_rss_kb,
            }
        )
    )


if __name__ == "__main__":
    main()
