from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from src.data.atas_history_bridge import AtasHistoryExportError, ingest_atas_history_export


def _write_export(path: Path, *, complete: bool = True, bid: str = "79999") -> str:
    records = [
        {
            "record_type": "header",
            "schema_version": 1,
            "source": "atas",
            "connector": "Bybit",
            "instrument": "BTCUSDT",
            "requested_from_utc": "2026-08-20T00:00:00Z",
            "requested_to_utc": "2026-08-21T00:00:00Z",
            "exported_at_utc": "2026-08-26T15:00:00Z",
        },
        {
            "record_type": "cumulative_trade",
            "timestamp_utc": "2026-08-20T00:00:01Z",
            "first_price": "80000.1",
            "last_price": "80000.2",
            "volume": "1.25",
            "direction": "BUY",
            "tick_count": 2,
        },
        {
            "record_type": "market_depth_snapshot",
            "timestamp_utc": "2026-08-20T00:00:02Z",
            "bids": [[bid, "2.0"], ["79998", "1.0"]],
            "asks": [["80001", "3.0"], ["80002", "1.5"]],
        },
        {
            "record_type": "footer",
            "complete": complete,
            "cumulative_trade_count": 1,
            "market_depth_snapshot_count": 1,
        },
    ]
    raw = "".join(json.dumps(item, sort_keys=True) + "\n" for item in records).encode()
    path.write_bytes(raw)
    return hashlib.sha256(raw).hexdigest()


def test_lands_valid_export_content_addressed_and_idempotently(tmp_path: Path) -> None:
    export = tmp_path / "export.jsonl"
    data = tmp_path / "lake"
    digest = _write_export(export)

    first = ingest_atas_history_export(export, data, expected_sha256=digest)
    second = ingest_atas_history_export(export, data, expected_sha256=digest)

    assert first == second
    assert first.source == "atas"
    assert first.cumulative_trade_count == 1
    landed = data / first.relative_export_path
    assert landed.read_bytes() == export.read_bytes()
    assert landed.with_suffix(".manifest.json").is_file()


def test_rejects_incomplete_export(tmp_path: Path) -> None:
    export = tmp_path / "export.jsonl"
    _write_export(export, complete=False)

    with pytest.raises(AtasHistoryExportError, match="footer is not complete"):
        ingest_atas_history_export(export, tmp_path / "lake")


def test_rejects_crossed_depth(tmp_path: Path) -> None:
    export = tmp_path / "export.jsonl"
    _write_export(export, bid="80001")

    with pytest.raises(AtasHistoryExportError, match="crossed depth snapshot"):
        ingest_atas_history_export(export, tmp_path / "lake")


def test_rejects_checksum_mismatch(tmp_path: Path) -> None:
    export = tmp_path / "export.jsonl"
    _write_export(export)

    with pytest.raises(AtasHistoryExportError, match="SHA-256 does not match"):
        ingest_atas_history_export(
            export, tmp_path / "lake", expected_sha256="0" * 64
        )
