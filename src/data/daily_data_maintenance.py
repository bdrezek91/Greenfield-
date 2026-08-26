"""Deterministic daily Silver quality and catalog maintenance evidence."""

from __future__ import annotations

import hashlib
import json
import os
import re
import uuid
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

import pandas as pd

from src.data.data_quality import build_daily_quality_report, write_quality_evidence
from src.data.dataset_catalog import build_dataset_snapshot, write_dataset_snapshot
from src.data.normalized_store import discover_normalized_manifests

_UTC_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_CODE_VERSION = re.compile(r"^[A-Za-z0-9_.-]+$")


class DailyDataMaintenanceError(RuntimeError):
    """Daily maintenance input or immutable evidence is unsafe."""


@dataclass(frozen=True, slots=True)
class CatalogEvidence:
    exchange: str
    market_type: str
    dataset_version: str
    snapshot_path: str
    snapshot_sha256: str
    eligible_row_count: int
    part_count: int


@dataclass(frozen=True, slots=True)
class DailyDataMaintenanceReport:
    schema_version: int
    maintenance_id: str
    utc_date: str
    cutoff_utc: str
    code_version: str
    qualified: bool
    quality_qualified: bool
    quality_report_path: str
    quality_report_sha256: str
    partition_count: int
    total_rows: int
    catalog_snapshots: tuple[CatalogEvidence, ...]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def run_daily_data_maintenance(
    data_dir: Path,
    *,
    utc_date: str,
    code_version: str,
) -> DailyDataMaintenanceReport:
    """Audit one UTC partition day and catalog every observed venue/market pair."""
    if not _UTC_DATE.fullmatch(utc_date):
        raise DailyDataMaintenanceError("utc_date must use YYYY-MM-DD")
    if not _CODE_VERSION.fullmatch(code_version):
        raise DailyDataMaintenanceError("code_version contains unsafe characters")
    try:
        day = pd.Timestamp(utc_date, tz="UTC")
    except ValueError as exc:
        raise DailyDataMaintenanceError("utc_date is not a calendar date") from exc
    if day.strftime("%Y-%m-%d") != utc_date:
        raise DailyDataMaintenanceError("utc_date is not a canonical calendar date")
    cutoff = day + pd.Timedelta(days=1)
    root = Path(data_dir).resolve(strict=True)

    quality = build_daily_quality_report(root, utc_date=utc_date, observed_at=cutoff)
    quality_path, _ = write_quality_evidence(root, quality)
    quality_sha256 = hashlib.sha256(quality_path.read_bytes()).hexdigest()

    catalog_evidence: list[CatalogEvidence] = []
    if quality.qualified:
        identities = sorted(
            {
                (manifest.exchange, manifest.market_type)
                for manifest in discover_normalized_manifests(root, utc_date=utc_date)
            }
        )
        for exchange, market_type in identities:
            snapshot = build_dataset_snapshot(
                root,
                as_of=cutoff,
                code_version=code_version,
                exchange=exchange,
                market_type=market_type,
            )
            snapshot_path = write_dataset_snapshot(root, snapshot)
            catalog_evidence.append(
                CatalogEvidence(
                    exchange=exchange,
                    market_type=market_type,
                    dataset_version=snapshot.dataset_version,
                    snapshot_path=str(snapshot_path.relative_to(root)),
                    snapshot_sha256=hashlib.sha256(snapshot_path.read_bytes()).hexdigest(),
                    eligible_row_count=snapshot.eligible_row_count,
                    part_count=snapshot.part_count,
                )
            )

    identity = {
        "schema_version": 1,
        "utc_date": utc_date,
        "cutoff_utc": cutoff.isoformat(),
        "code_version": code_version,
        "quality_report_sha256": quality_sha256,
        "catalog_snapshots": [asdict(item) for item in catalog_evidence],
    }
    maintenance_id = hashlib.sha256(
        json.dumps(identity, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    return DailyDataMaintenanceReport(
        maintenance_id=maintenance_id,
        qualified=quality.qualified and bool(catalog_evidence),
        quality_qualified=quality.qualified,
        quality_report_path=str(quality_path.relative_to(root)),
        partition_count=quality.partition_count,
        total_rows=quality.total_rows,
        catalog_snapshots=tuple(catalog_evidence),
        **{key: value for key, value in identity.items() if key != "catalog_snapshots"},
    )


def write_daily_data_maintenance_report(
    data_dir: Path, report: DailyDataMaintenanceReport
) -> Path:
    root = Path(data_dir).resolve(strict=True)
    path = root / "maintenance" / "v1" / "daily" / f"{report.maintenance_id}.json"
    document = json.dumps(report.to_dict(), sort_keys=True, indent=2) + "\n"
    if path.exists():
        if path.read_text(encoding="utf-8") != document:
            raise DailyDataMaintenanceError("immutable daily maintenance collision")
        return path
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    try:
        with temporary.open("x", encoding="utf-8", newline="\n") as handle:
            handle.write(document)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)
    return path
