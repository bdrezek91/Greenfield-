"""Fail-closed Silver quality reports and non-destructive quarantine overlays."""

from __future__ import annotations

import hashlib
import json
import os
import re
import uuid
from dataclasses import asdict, dataclass
from pathlib import Path

import pandas as pd

from src.data.normalized_event import NormalizedMarketEvent
from src.data.normalized_store import (
    NormalizedPartManifest,
    discover_normalized_manifests,
    read_normalized_part,
    verify_normalized_part,
)

_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_DEFAULT_MAX_CLOCK_LEAD = pd.Timedelta(seconds=5)


@dataclass(frozen=True, slots=True)
class QualityCheck:
    name: str
    passed: bool
    severity: str
    detail: str


@dataclass(frozen=True, slots=True)
class PartitionQualityReport:
    schema_version: int
    observed_at_utc: str
    part_path: str
    content_sha256: str
    row_count: int
    qualified: bool
    checks: tuple[QualityCheck, ...]

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class DailyQualityReport:
    schema_version: int
    utc_date: str
    observed_at_utc: str
    partition_count: int
    qualified_partition_count: int
    quarantined_partition_count: int
    total_rows: int
    qualified: bool
    partitions_sha256: str
    partitions: tuple[PartitionQualityReport, ...]

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


class QualityError(RuntimeError):
    """Quality evidence is invalid or would overwrite different evidence."""


def assess_normalized_part(
    data_dir: Path,
    manifest: NormalizedPartManifest,
    *,
    observed_at: pd.Timestamp,
    max_exchange_clock_lead: pd.Timedelta = _DEFAULT_MAX_CLOCK_LEAD,
) -> PartitionQualityReport:
    observed = _utc_timestamp(observed_at)
    checks: list[QualityCheck] = []
    try:
        verify_normalized_part(data_dir, manifest)
        rows = read_normalized_part(data_dir, manifest)
        checks.append(QualityCheck("immutable_integrity", True, "fatal", "verified"))
    except Exception as exc:  # noqa: BLE001 - corruption becomes report evidence
        checks.append(QualityCheck("immutable_integrity", False, "fatal", str(exc)))
        return _partition_report(manifest, observed, checks)

    checks.extend(
        (
            QualityCheck("non_empty", bool(rows), "fatal", f"rows={len(rows)}"),
            _unique_ids_check(rows),
            _ordering_check(rows),
            _identity_check(rows, manifest),
            _lineage_check(rows),
            _record_contract_check(rows),
            _timestamp_check(rows, observed, max_exchange_clock_lead),
        )
    )
    return _partition_report(manifest, observed, checks)


def build_daily_quality_report(
    data_dir: Path,
    *,
    utc_date: str,
    observed_at: pd.Timestamp,
) -> DailyQualityReport:
    observed = _utc_timestamp(observed_at)
    manifests = discover_normalized_manifests(data_dir, utc_date=utc_date)
    reports = tuple(
        assess_normalized_part(data_dir, manifest, observed_at=observed)
        for manifest in manifests
    )
    qualified_count = sum(report.qualified for report in reports)
    material = "\n".join(
        f"{report.part_path}|{report.content_sha256}|{report.qualified}" for report in reports
    )
    return DailyQualityReport(
        schema_version=1,
        utc_date=utc_date,
        observed_at_utc=observed.isoformat(),
        partition_count=len(reports),
        qualified_partition_count=qualified_count,
        quarantined_partition_count=len(reports) - qualified_count,
        total_rows=sum(report.row_count for report in reports),
        qualified=bool(reports) and qualified_count == len(reports),
        partitions_sha256=hashlib.sha256(material.encode("utf-8")).hexdigest(),
        partitions=reports,
    )


def write_quality_evidence(
    data_dir: Path,
    report: DailyQualityReport,
) -> tuple[Path, tuple[Path, ...]]:
    """Write an immutable daily report and overlays for every failed part."""
    root = Path(data_dir) / "quality" / "v1"
    report_path = root / "daily" / f"{report.utc_date}.json"
    _write_idempotent(report_path, _json(report.to_dict()))
    quarantine_paths = []
    for partition in report.partitions:
        if partition.qualified:
            continue
        identity = hashlib.sha256(partition.part_path.encode("utf-8")).hexdigest()
        path = root / "quarantine" / f"{identity}.json"
        payload = {
            "schema_version": 1,
            "status": "quarantined",
            "policy": "overlay-do-not-move-immutable-part",
            "partition": partition.to_dict(),
        }
        _write_idempotent(path, _json(payload))
        quarantine_paths.append(path)
    return report_path, tuple(quarantine_paths)


def _partition_report(
    manifest: NormalizedPartManifest,
    observed: pd.Timestamp,
    checks: list[QualityCheck],
) -> PartitionQualityReport:
    qualified = all(check.passed for check in checks if check.severity == "fatal")
    return PartitionQualityReport(
        schema_version=1,
        observed_at_utc=observed.isoformat(),
        part_path=manifest.part_path,
        content_sha256=manifest.content_sha256,
        row_count=manifest.row_count,
        qualified=qualified,
        checks=tuple(checks),
    )


def _unique_ids_check(rows: list[NormalizedMarketEvent]) -> QualityCheck:
    duplicates = len(rows) - len({row.normalized_id for row in rows})
    return QualityCheck(
        "unique_normalized_ids", duplicates == 0, "fatal", f"duplicates={duplicates}"
    )


def _ordering_check(rows: list[NormalizedMarketEvent]) -> QualityCheck:
    keys = [
        (row.receive_ts_ns, row.receive_sequence, row.row_index, row.normalized_id)
        for row in rows
    ]
    return QualityCheck("deterministic_order", keys == sorted(keys), "fatal", f"rows={len(keys)}")


def _identity_check(
    rows: list[NormalizedMarketEvent], manifest: NormalizedPartManifest
) -> QualityCheck:
    expected = (manifest.exchange, manifest.market_type, manifest.channel, manifest.symbol)
    mismatches = sum(
        (row.exchange, row.market_type, row.channel, row.symbol) != expected for row in rows
    )
    return QualityCheck("partition_identity", mismatches == 0, "fatal", f"mismatches={mismatches}")


def _lineage_check(rows: list[NormalizedMarketEvent]) -> QualityCheck:
    invalid = sum(
        not _SHA256.fullmatch(row.raw_event_id)
        or not _SHA256.fullmatch(row.raw_payload_sha256)
        for row in rows
    )
    return QualityCheck("raw_lineage", invalid == 0, "fatal", f"invalid={invalid}")


def _record_contract_check(rows: list[NormalizedMarketEvent]) -> QualityCheck:
    invalid = 0
    for row in rows:
        if row.record_type == "trade":
            valid = all((row.side, row.price, row.size, row.trade_id))
        elif row.record_type == "book_level":
            valid = all((row.book_side, row.book_action, row.price, row.size))
        elif row.record_type == "liquidation":
            valid = all((row.side, row.price, row.size))
        elif row.record_type == "ticker_metric":
            valid = bool(row.metric_name and row.metric_value is not None)
        else:
            valid = False
        invalid += not valid
    return QualityCheck("record_contract", invalid == 0, "fatal", f"invalid={invalid}")


def _timestamp_check(
    rows: list[NormalizedMarketEvent],
    observed: pd.Timestamp,
    max_exchange_clock_lead: pd.Timedelta,
) -> QualityCheck:
    observed_ms = int(observed.timestamp() * 1000)
    allowed_lead_ms = int(max_exchange_clock_lead.total_seconds() * 1000)
    invalid = sum(
        row.event_ts_ms > observed_ms
        or row.event_ts_ms > row.receive_ts_ns // 1_000_000 + allowed_lead_ms
        for row in rows
    )
    return QualityCheck("causal_timestamps", invalid == 0, "fatal", f"invalid={invalid}")


def _utc_timestamp(value: pd.Timestamp) -> pd.Timestamp:
    timestamp = pd.Timestamp(value)
    if timestamp.tzinfo is None:
        raise QualityError("observed_at must be timezone-aware")
    return timestamp.tz_convert("UTC")


def _json(value: object) -> str:
    return json.dumps(value, sort_keys=True, indent=2) + "\n"


def _write_idempotent(path: Path, value: str) -> None:
    if path.exists():
        if path.read_text(encoding="utf-8") != value:
            raise QualityError(f"immutable quality evidence collision: {path}")
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    try:
        with temp.open("w", encoding="utf-8", newline="\n") as handle:
            handle.write(value)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp, path)
    finally:
        temp.unlink(missing_ok=True)
