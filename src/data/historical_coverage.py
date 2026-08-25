"""Coverage and integrity evidence for the bounded historical REST backfill."""

from __future__ import annotations

import json
import os
import uuid
from dataclasses import asdict, dataclass
from datetime import UTC, date, datetime
from pathlib import Path

import pandas as pd

from src.data.historical_backfill import HistoricalBackfillJob

_INTERVAL_SECONDS = {
    "1m": 60,
    "5m": 300,
    "5min": 300,
    "15m": 900,
    "1h": 3_600,
    "4h": 14_400,
    "1d": 86_400,
}


@dataclass(frozen=True, slots=True)
class HistoricalCoverageItem:
    identity: str
    requested_start_utc: str
    requested_end_utc: str
    partition_count: int
    row_count: int
    first_timestamp_utc: str | None
    last_timestamp_utc: str | None
    duplicate_timestamp_count: int
    gap_count: int
    maximum_gap_seconds: float | None
    approximate_coverage_ratio: float
    status: str
    errors: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class HistoricalCoverageReport:
    schema_version: int
    qualified: bool
    as_of_utc: str
    job_count: int
    full_job_count: int
    partial_job_count: int
    missing_job_count: int
    items: tuple[HistoricalCoverageItem, ...]

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


def audit_historical_coverage(
    data_dir: Path,
    jobs: tuple[HistoricalBackfillJob, ...],
    *,
    as_of: datetime,
) -> HistoricalCoverageReport:
    if as_of.tzinfo is None:
        raise ValueError("historical coverage as_of must be timezone-aware")
    items = tuple(_audit_job(data_dir, job) for job in jobs)
    statuses = [item.status for item in items]
    return HistoricalCoverageReport(
        schema_version=1,
        qualified=bool(items)
        and all(not item.errors and item.status != "MISSING" for item in items),
        as_of_utc=as_of.astimezone(UTC).isoformat(),
        job_count=len(items),
        full_job_count=statuses.count("FULL"),
        partial_job_count=statuses.count("PARTIAL"),
        missing_job_count=statuses.count("MISSING"),
        items=items,
    )


def write_historical_coverage_report(
    path: Path, report: HistoricalCoverageReport
) -> None:
    value = json.dumps(report.to_dict(), sort_keys=True, indent=2) + "\n"
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    try:
        with temp_path.open("x", encoding="utf-8", newline="\n") as handle:
            handle.write(value)
            handle.flush()
            os.fsync(handle.fileno())
        os.link(temp_path, path)
    except FileExistsError as exc:
        raise FileExistsError(
            f"historical coverage report already exists and will not be overwritten: {path}"
        ) from exc
    finally:
        temp_path.unlink(missing_ok=True)


def _audit_job(data_dir: Path, job: HistoricalBackfillJob) -> HistoricalCoverageItem:
    interval_seconds = _job_interval_seconds(job)
    start = _midnight(job.start)
    end = _midnight(job.end)
    paths = sorted(_job_root(data_dir, job).glob("*.parquet"))
    frames: list[pd.DataFrame] = []
    errors: list[str] = []
    expected_symbol = job.venue_symbol if job.venue == "okx" else job.symbol
    for path in paths:
        try:
            columns = ["timestamp", "symbol"]
            if job.dataset == "klines":
                columns.append("timeframe")
            frame = pd.read_parquet(path, columns=columns)
        except (OSError, ValueError) as exc:
            errors.append(f"unreadable partition {path.name}: {exc}")
            continue
        if not frame.empty and set(frame["symbol"].astype(str)) != {expected_symbol}:
            errors.append(f"unexpected symbol in {path.name}")
        if job.dataset == "klines" and not frame.empty:
            if set(frame["timeframe"].astype(str)) != {job.timeframe}:
                errors.append(f"unexpected timeframe in {path.name}")
        frames.append(frame[["timestamp"]])
    requested_rows = max(1, int((end - start).total_seconds() // interval_seconds) + 1)
    if not frames:
        return HistoricalCoverageItem(
            identity=job.identity,
            requested_start_utc=start.isoformat(),
            requested_end_utc=end.isoformat(),
            partition_count=len(paths),
            row_count=0,
            first_timestamp_utc=None,
            last_timestamp_utc=None,
            duplicate_timestamp_count=0,
            gap_count=0,
            maximum_gap_seconds=None,
            approximate_coverage_ratio=0.0,
            status="MISSING",
            errors=tuple(errors),
        )
    combined = pd.concat(frames, ignore_index=True)
    timestamps = pd.to_datetime(combined["timestamp"], utc=True, errors="coerce")
    invalid_count = int(timestamps.isna().sum())
    if invalid_count:
        errors.append(f"invalid timestamps: {invalid_count}")
    timestamps = timestamps.dropna().sort_values().reset_index(drop=True)
    duplicates = int(timestamps.duplicated().sum())
    if duplicates:
        errors.append(f"duplicate timestamps: {duplicates}")
    deltas = timestamps.diff().dt.total_seconds().dropna()
    gaps = deltas[deltas > interval_seconds * 1.5]
    first = timestamps.iloc[0] if not timestamps.empty else None
    last = timestamps.iloc[-1] if not timestamps.empty else None
    full = bool(
        first is not None
        and last is not None
        and first <= start + pd.Timedelta(seconds=interval_seconds)
        and last >= end - pd.Timedelta(seconds=interval_seconds)
    )
    return HistoricalCoverageItem(
        identity=job.identity,
        requested_start_utc=start.isoformat(),
        requested_end_utc=end.isoformat(),
        partition_count=len(paths),
        row_count=len(timestamps),
        first_timestamp_utc=first.isoformat() if first is not None else None,
        last_timestamp_utc=last.isoformat() if last is not None else None,
        duplicate_timestamp_count=duplicates,
        gap_count=len(gaps),
        maximum_gap_seconds=float(deltas.max()) if not deltas.empty else None,
        approximate_coverage_ratio=min(1.0, len(timestamps) / requested_rows),
        status="FULL" if full else "PARTIAL",
        errors=tuple(errors),
    )


def _job_root(data_dir: Path, job: HistoricalBackfillJob) -> Path:
    if job.dataset == "klines":
        prefix = {"bybit": "klines", "binance": "binance_klines", "okx": "okx_klines"}[
            job.venue
        ]
        symbol = job.venue_symbol if job.venue == "okx" else job.symbol
        return data_dir / prefix / symbol / str(job.timeframe)
    if job.dataset == "funding":
        return data_dir / "funding" / job.symbol
    return data_dir / "open_interest" / job.symbol / str(job.timeframe)


def _job_interval_seconds(job: HistoricalBackfillJob) -> int:
    if job.dataset == "funding":
        return 8 * 3_600
    try:
        return _INTERVAL_SECONDS[str(job.timeframe)]
    except KeyError as exc:
        raise ValueError(f"unknown historical interval {job.timeframe!r}") from exc


def _midnight(value: date) -> pd.Timestamp:
    return pd.Timestamp(value, tz="UTC")
