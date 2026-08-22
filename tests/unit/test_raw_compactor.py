"""Raw compaction creates a verified mirror and preserves every source byte."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from src.data.raw_compactor import compact_raw_partition
from src.data.raw_event import parse_bybit_message
from src.data.raw_store import AtomicRawWriter, load_raw_events


def _event(receive_ts_ns: int, update_id: int):
    payload = json.dumps(
        {
            "topic": "orderbook.50.BTCUSDT",
            "type": "snapshot",
            "ts": 1_700_000_000_000,
            "data": {
                "s": "BTCUSDT",
                "b": [["100", "1"]],
                "a": [["101", "1"]],
                "u": update_id,
                "seq": update_id,
            },
        },
        separators=(",", ":"),
    )
    return parse_bybit_message(
        payload,
        receive_ts_ns=receive_ts_ns,
        receive_sequence=update_id,
        connection_id="connection-1",
    )


def _checksum(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_compaction_is_event_identical_and_non_destructive(tmp_path: Path) -> None:
    writer = AtomicRawWriter(tmp_path)
    first = writer.write([_event(1_700_000_000_000_000_001, 1)])[0]
    second = writer.write([_event(1_700_000_000_000_000_002, 2)])[0]
    source_paths = [tmp_path / first.part_path, tmp_path / second.part_path]
    before = {path: _checksum(path) for path in source_paths}

    report = compact_raw_partition(
        tmp_path,
        exchange="bybit",
        market_type="linear",
        channel="orderbook",
        symbol="BTCUSDT",
        utc_date="2023-11-14",
    )

    assert report.source_part_count == 2
    assert report.source_row_count == report.compacted_row_count == 2
    assert report.source_events_sha256 == report.compacted_events_sha256
    assert {path: _checksum(path) for path in source_paths} == before
    compacted = load_raw_events(
        tmp_path / "raw_compacted", channel="orderbook", symbol="BTCUSDT"
    )
    assert [event.update_id for event in compacted] == [1, 2]
