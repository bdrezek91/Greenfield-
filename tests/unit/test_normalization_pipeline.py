"""The lake pipeline verifies Bronze and idempotently materializes Silver."""

from __future__ import annotations

import json
from pathlib import Path

from src.data.normalization_pipeline import normalize_raw_lake
from src.data.raw_event import parse_bybit_message
from src.data.raw_store import AtomicRawWriter


def _event(message: dict, sequence: int):
    return parse_bybit_message(
        json.dumps(message, separators=(",", ":")),
        receive_ts_ns=1_700_000_000_000_000_000 + sequence,
        receive_sequence=sequence,
        connection_id="c",
    )


def test_pipeline_is_idempotent_and_reports_lineage(tmp_path: Path) -> None:
    source = tmp_path / "bronze"
    output = tmp_path / "silver"
    events = [
        _event({"success": True, "op": "subscribe"}, 1),
        _event(
            {
                "topic": "publicTrade.BTCUSDT",
                "type": "snapshot",
                "ts": 1_700_000_000_002,
                "data": [
                    {
                        "T": 1_700_000_000_001,
                        "s": "BTCUSDT",
                        "S": "Buy",
                        "v": "1",
                        "p": "2",
                        "i": "trade-1",
                    }
                ],
            },
            2,
        ),
    ]
    AtomicRawWriter(source).write(events)

    first = normalize_raw_lake(source, output)
    second = normalize_raw_lake(source, output)

    assert first == second
    assert first.source_part_count == 2
    assert first.source_raw_event_count == 2
    assert first.normalized_part_count == 1
    assert first.normalized_row_count == 1
    assert first.skipped_control_count == 1
    assert first.raw_channel_counts == {"control": 1, "trades": 1}
    assert first.normalized_record_counts == {"trade": 1}
    assert len(first.normalized_parts) == 1


def test_pipeline_filters_symbol(tmp_path: Path) -> None:
    source = tmp_path / "bronze"
    output = tmp_path / "silver"
    AtomicRawWriter(source).write(
        [
            _event(
                {
                    "topic": f"publicTrade.{symbol}",
                    "type": "snapshot",
                    "ts": 1_700_000_000_002,
                    "data": [
                        {
                            "T": 1_700_000_000_001,
                            "s": symbol,
                            "S": "Buy",
                            "v": "1",
                            "p": "2",
                            "i": symbol,
                        }
                    ],
                },
                index,
            )
            for index, symbol in enumerate(("BTCUSDT", "ETHUSDT"), start=1)
        ]
    )

    report = normalize_raw_lake(source, output, symbol="ETHUSDT")

    assert report.source_raw_event_count == 1
    assert report.normalized_row_count == 1
    assert "symbol=ETHUSDT" in report.normalized_parts[0]
