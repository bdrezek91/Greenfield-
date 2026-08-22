"""Silver quality evidence fails closed and quarantines without moving data."""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import pytest

from src.data.data_quality import (
    QualityError,
    assess_normalized_part,
    build_daily_quality_report,
    write_quality_evidence,
)
from src.data.normalized_event import normalize_bybit_event
from src.data.normalized_store import AtomicNormalizedWriter
from src.data.raw_event import parse_bybit_message


def _write_trade_part(root: Path):
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
                        "i": "trade-1",
                    }
                ],
            },
            separators=(",", ":"),
        ),
        receive_ts_ns=1_700_000_000_011_000_000,
        receive_sequence=1,
        connection_id="c",
    )
    manifest = AtomicNormalizedWriter(root).write_source_part(
        list(normalize_bybit_event(raw)),
        source_events_sha256="a" * 64,
        source_part_path="raw/source.parquet",
        utc_date="2023-11-14",
    )
    assert manifest is not None
    return manifest


def test_valid_partition_and_daily_report_qualify(tmp_path: Path) -> None:
    manifest = _write_trade_part(tmp_path)
    observed = pd.Timestamp("2023-11-15T00:00:00Z")

    partition = assess_normalized_part(tmp_path, manifest, observed_at=observed)
    daily = build_daily_quality_report(
        tmp_path, utc_date="2023-11-14", observed_at=observed
    )
    report_path, quarantine = write_quality_evidence(tmp_path, daily)

    assert partition.qualified is True
    assert all(check.passed for check in partition.checks)
    assert daily.qualified is True
    assert daily.partition_count == 1
    assert daily.total_rows == 1
    assert report_path.is_file()
    assert quarantine == ()
    assert Path(tmp_path, manifest.part_path).is_file()
    assert write_quality_evidence(tmp_path, daily) == (report_path, ())


def test_corrupt_partition_gets_overlay_quarantine_without_move(tmp_path: Path) -> None:
    manifest = _write_trade_part(tmp_path)
    part_path = Path(tmp_path, manifest.part_path)
    part_path.write_bytes(b"corrupt")

    daily = build_daily_quality_report(
        tmp_path,
        utc_date="2023-11-14",
        observed_at=pd.Timestamp("2023-11-15T00:00:00Z"),
    )
    _, quarantine = write_quality_evidence(tmp_path, daily)

    assert daily.qualified is False
    assert daily.quarantined_partition_count == 1
    assert len(quarantine) == 1
    payload = json.loads(quarantine[0].read_text())
    assert payload["status"] == "quarantined"
    assert payload["policy"] == "overlay-do-not-move-immutable-part"
    assert part_path.is_file()
    assert part_path.read_bytes() == b"corrupt"


def test_future_exchange_timestamp_fails_causal_check(tmp_path: Path) -> None:
    manifest = _write_trade_part(tmp_path)
    report = assess_normalized_part(
        tmp_path,
        manifest,
        observed_at=pd.Timestamp("2023-11-14T00:00:00Z"),
    )

    assert report.qualified is False
    causal = next(check for check in report.checks if check.name == "causal_timestamps")
    assert causal.passed is False


def test_daily_evidence_refuses_different_overwrite(tmp_path: Path) -> None:
    _write_trade_part(tmp_path)
    first = build_daily_quality_report(
        tmp_path,
        utc_date="2023-11-14",
        observed_at=pd.Timestamp("2023-11-15T00:00:00Z"),
    )
    write_quality_evidence(tmp_path, first)
    second = build_daily_quality_report(
        tmp_path,
        utc_date="2023-11-14",
        observed_at=pd.Timestamp("2023-11-15T00:01:00Z"),
    )

    with pytest.raises(QualityError, match="collision"):
        write_quality_evidence(tmp_path, second)
