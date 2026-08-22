"""Silver parts are immutable, checksummed, and idempotent per Bronze part."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.data.normalized_event import normalize_bybit_event
from src.data.normalized_store import (
    AtomicNormalizedWriter,
    NormalizedStoreError,
    read_normalized_part,
    verify_normalized_part,
)
from src.data.raw_event import parse_bybit_message


def _trade_rows():
    raw = parse_bybit_message(
        json.dumps(
            {
                "topic": "publicTrade.BTCUSDT",
                "type": "snapshot",
                "ts": 1_700_000_000_010,
                "data": [
                    {
                        "T": 1_700_000_000_009,
                        "s": "BTCUSDT",
                        "S": "Buy",
                        "v": "1",
                        "p": "2",
                        "i": "a",
                    },
                    {
                        "T": 1_700_000_000_010,
                        "s": "BTCUSDT",
                        "S": "Sell",
                        "v": "3",
                        "p": "4",
                        "i": "b",
                    },
                ],
            },
            separators=(",", ":"),
        ),
        receive_ts_ns=1_700_000_000_011_000_000,
        receive_sequence=1,
        connection_id="c",
    )
    return list(normalize_bybit_event(raw))


def test_round_trip_and_idempotent_rewrite(tmp_path: Path) -> None:
    rows = _trade_rows()
    writer = AtomicNormalizedWriter(tmp_path)

    first = writer.write_source_part(
        rows,
        source_events_sha256="a" * 64,
        source_part_path="raw/source.parquet",
        utc_date="2023-11-14",
    )
    second = writer.write_source_part(
        list(reversed(rows)),
        source_events_sha256="a" * 64,
        source_part_path="raw/source.parquet",
        utc_date="2023-11-14",
    )

    assert first is not None
    assert first == second
    verify_normalized_part(tmp_path, first)
    assert read_normalized_part(tmp_path, first) == rows
    assert "channel=trades" in first.part_path
    assert Path(tmp_path, first.manifest_path).is_file()


def test_tampering_is_detected(tmp_path: Path) -> None:
    manifest = AtomicNormalizedWriter(tmp_path).write_source_part(
        _trade_rows(),
        source_events_sha256="b" * 64,
        source_part_path="raw/source.parquet",
        utc_date="2023-11-14",
    )
    assert manifest is not None
    Path(tmp_path, manifest.part_path).write_bytes(b"changed")

    with pytest.raises(NormalizedStoreError, match="checksum mismatch"):
        verify_normalized_part(tmp_path, manifest)


def test_mixed_streams_are_rejected(tmp_path: Path) -> None:
    rows = _trade_rows()
    changed = rows[0].to_record()
    changed["symbol"] = "ETHUSDT"
    mixed = [rows[0], type(rows[0])(**changed)]

    with pytest.raises(NormalizedStoreError, match="one market stream"):
        AtomicNormalizedWriter(tmp_path).write_source_part(
            mixed,
            source_events_sha256="c" * 64,
            source_part_path="raw/source.parquet",
            utc_date="2023-11-14",
        )


def test_empty_control_source_creates_no_part(tmp_path: Path) -> None:
    assert (
        AtomicNormalizedWriter(tmp_path).write_source_part(
            [],
            source_events_sha256="d" * 64,
            source_part_path="raw/control.parquet",
            utc_date="2023-11-14",
        )
        is None
    )
