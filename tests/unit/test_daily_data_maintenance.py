"""Daily Silver maintenance composes quality and catalog evidence safely."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.data.daily_data_maintenance import (
    DailyDataMaintenanceError,
    run_daily_data_maintenance,
    write_daily_data_maintenance_report,
)
from src.data.normalized_event import normalize_bybit_event
from src.data.normalized_store import AtomicNormalizedWriter
from src.data.raw_event import parse_bybit_message


def _write_trade(
    root: Path,
    *,
    utc_date: str = "2023-11-14",
    source_events_sha256: str = "a" * 64,
    source_part_path: str = "raw/source.parquet",
) -> None:
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
            }
        ),
        receive_ts_ns=1_700_000_000_011_000_000,
        receive_sequence=1,
        connection_id="c",
    )
    manifest = AtomicNormalizedWriter(root).write_source_part(
        list(normalize_bybit_event(raw)),
        source_events_sha256=source_events_sha256,
        source_part_path=source_part_path,
        utc_date=utc_date,
    )
    assert manifest is not None


def test_daily_maintenance_is_reproducible_and_qualified(tmp_path: Path) -> None:
    _write_trade(tmp_path)

    first = run_daily_data_maintenance(
        tmp_path, utc_date="2023-11-14", code_version="abc123"
    )
    first_path = write_daily_data_maintenance_report(tmp_path, first)
    second = run_daily_data_maintenance(
        tmp_path, utc_date="2023-11-14", code_version="abc123"
    )

    assert first == second
    assert first.qualified is True
    assert first.quality_qualified is True
    assert first.partition_count == 1
    assert first.total_rows == 1
    assert len(first.catalog_snapshots) == 1
    assert first.catalog_snapshots[0].exchange == "bybit"
    assert first.catalog_snapshots[0].market_type == "linear"
    assert write_daily_data_maintenance_report(tmp_path, second) == first_path


def test_daily_maintenance_fails_closed_without_partitions(tmp_path: Path) -> None:
    report = run_daily_data_maintenance(
        tmp_path, utc_date="2023-11-14", code_version="abc123"
    )

    assert report.qualified is False
    assert report.quality_qualified is False
    assert report.catalog_snapshots == ()
    assert write_daily_data_maintenance_report(tmp_path, report).is_file()


def test_daily_catalog_scope_matches_the_quality_day(tmp_path: Path) -> None:
    _write_trade(tmp_path)
    _write_trade(
        tmp_path,
        utc_date="2023-11-13",
        source_events_sha256="b" * 64,
        source_part_path="raw/older-source.parquet",
    )

    report = run_daily_data_maintenance(
        tmp_path, utc_date="2023-11-14", code_version="abc123"
    )

    assert report.qualified is True
    assert len(report.catalog_snapshots) == 1
    assert report.catalog_snapshots[0].eligible_row_count == 1
    snapshot = json.loads(
        (tmp_path / report.catalog_snapshots[0].snapshot_path).read_text(encoding="utf-8")
    )
    assert snapshot["utc_date"] == "2023-11-14"


@pytest.mark.parametrize("utc_date", ["2023-1-1", "2023-02-30", "../escape"])
def test_daily_maintenance_rejects_unsafe_dates(tmp_path: Path, utc_date: str) -> None:
    with pytest.raises(DailyDataMaintenanceError):
        run_daily_data_maintenance(tmp_path, utc_date=utc_date, code_version="abc123")


def test_daily_maintenance_rejects_unsafe_code_version(tmp_path: Path) -> None:
    with pytest.raises(DailyDataMaintenanceError, match="unsafe"):
        run_daily_data_maintenance(
            tmp_path, utc_date="2023-11-14", code_version="../../main"
        )
