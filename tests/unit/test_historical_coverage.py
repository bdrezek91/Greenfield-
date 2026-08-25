from datetime import UTC, date, datetime
from pathlib import Path

import pandas as pd
import pytest

from src.data.historical_backfill import HistoricalBackfillJob
from src.data.historical_coverage import (
    audit_historical_coverage,
    write_historical_coverage_report,
)


def _job() -> HistoricalBackfillJob:
    return HistoricalBackfillJob(
        dataset="klines",
        venue="bybit",
        symbol="BTCUSDT",
        venue_symbol="BTCUSDT",
        timeframe="1h",
        start=date(2026, 1, 1),
        end=date(2026, 1, 1),
    )


def _write(path: Path, timestamps: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(
        {
            "timestamp": pd.to_datetime(timestamps, utc=True),
            "symbol": "BTCUSDT",
            "timeframe": "1h",
        }
    ).to_parquet(path, index=False)


def test_coverage_reports_full_unique_dataset(tmp_path: Path) -> None:
    _write(
        tmp_path / "klines/BTCUSDT/1h/2026-01.parquet",
        ["2026-01-01T00:00:00Z"],
    )
    report = audit_historical_coverage(
        tmp_path, (_job(),), as_of=datetime(2026, 1, 2, tzinfo=UTC)
    )
    assert report.qualified
    assert report.full_job_count == 1
    assert report.items[0].approximate_coverage_ratio == 1.0


def test_missing_and_duplicates_fail_closed(tmp_path: Path) -> None:
    missing = audit_historical_coverage(
        tmp_path, (_job(),), as_of=datetime(2026, 1, 2, tzinfo=UTC)
    )
    assert not missing.qualified
    assert missing.missing_job_count == 1

    _write(
        tmp_path / "klines/BTCUSDT/1h/2026-01.parquet",
        ["2026-01-01T00:00:00Z", "2026-01-01T00:00:00Z"],
    )
    duplicate = audit_historical_coverage(
        tmp_path, (_job(),), as_of=datetime(2026, 1, 2, tzinfo=UTC)
    )
    assert not duplicate.qualified
    assert duplicate.items[0].duplicate_timestamp_count == 1


def test_coverage_report_is_immutable(tmp_path: Path) -> None:
    report = audit_historical_coverage(
        tmp_path, (_job(),), as_of=datetime(2026, 1, 2, tzinfo=UTC)
    )
    path = tmp_path / "coverage.json"
    write_historical_coverage_report(path, report)
    with pytest.raises(FileExistsError, match="will not be overwritten"):
        write_historical_coverage_report(path, report)
