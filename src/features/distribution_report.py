"""Immutable empirical distribution evidence for one exact Gold dataset."""

from __future__ import annotations

import hashlib
import json
import math
import os
import re
import uuid
from dataclasses import asdict, dataclass
from pathlib import Path

import pandas as pd

from src.features.store import FeaturePartManifest, verify_feature_part

_SAFE = re.compile(r"^[A-Za-z0-9_.-]+$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")


class FeatureDistributionError(RuntimeError):
    """Gold distribution evidence is missing, mixed, or corrupt."""


@dataclass(frozen=True, slots=True)
class FeatureDistributionMetric:
    name: str
    count: int
    minimum: float
    q01: float
    q05: float
    median: float
    q95: float
    q99: float
    maximum: float
    mean: float
    standard_deviation: float
    zero_fraction: float
    unique_count: int


@dataclass(frozen=True, slots=True)
class FeatureDistributionReport:
    schema_version: int
    qualified: bool
    feature_set: str
    symbol: str
    dataset_version: str
    code_version: str
    manifest_count: int
    manifest_set_sha256: str
    row_count: int
    first_timestamp_utc: str
    last_timestamp_utc: str
    metrics: tuple[FeatureDistributionMetric, ...]
    warnings: tuple[str, ...]

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


def audit_feature_distribution(
    data_dir: Path,
    *,
    feature_set: str,
    symbol: str,
    dataset_version: str,
    code_version: str,
) -> FeatureDistributionReport:
    """Verify and summarize one immutable dataset/code tuple without tuning."""
    for value in (feature_set, symbol, code_version):
        if not _SAFE.fullmatch(value):
            raise FeatureDistributionError(f"unsafe feature identity: {value!r}")
    if not _SHA256.fullmatch(dataset_version):
        raise FeatureDistributionError("dataset_version must be a SHA-256")
    root = Path(data_dir)
    paths = sorted(
        root.glob(f"gold/v1/feature_set={feature_set}/symbol={symbol}/date=*/*.manifest.json")
    )
    manifests = []
    frames = []
    for path in paths:
        try:
            manifest = FeaturePartManifest.from_json(path.read_text(encoding="utf-8"))
        except (OSError, TypeError, ValueError) as exc:
            raise FeatureDistributionError(f"unreadable Gold manifest: {path}") from exc
        if manifest.dataset_version != dataset_version or manifest.code_version != code_version:
            continue
        if manifest.feature_set != feature_set or manifest.symbol != symbol:
            raise FeatureDistributionError("Gold manifest path and identity disagree")
        expected_manifest_path = path.relative_to(root).as_posix()
        if manifest.manifest_path != expected_manifest_path:
            raise FeatureDistributionError("Gold manifest location and part path disagree")
        verify_feature_part(root, manifest)
        manifests.append(manifest)
        frames.append(pd.read_parquet(root / manifest.part_path))
    if not manifests:
        raise FeatureDistributionError("no Gold manifests match the exact dataset/code tuple")
    columns = manifests[0].feature_columns
    if any(item.feature_columns != columns for item in manifests):
        raise FeatureDistributionError("Gold feature schemas differ across manifests")
    frame = pd.concat(frames, ignore_index=True).sort_values("timestamp").reset_index(drop=True)
    timestamps = pd.to_datetime(frame["timestamp"], utc=True)
    if timestamps.duplicated().any():
        raise FeatureDistributionError("duplicate feature timestamps across Gold manifests")
    metrics = tuple(_metric(name, frame[name]) for name in columns)
    warnings = tuple(
        f"CONSTANT_FEATURE:{metric.name}" for metric in metrics if metric.unique_count == 1
    )
    manifest_set_sha256 = _manifest_set_sha256(manifests)
    return FeatureDistributionReport(
        schema_version=1,
        qualified=True,
        feature_set=feature_set,
        symbol=symbol,
        dataset_version=dataset_version,
        code_version=code_version,
        manifest_count=len(manifests),
        manifest_set_sha256=manifest_set_sha256,
        row_count=len(frame),
        first_timestamp_utc=timestamps.iloc[0].isoformat(),
        last_timestamp_utc=timestamps.iloc[-1].isoformat(),
        metrics=metrics,
        warnings=warnings,
    )


def write_feature_distribution_report(data_dir: Path, report: FeatureDistributionReport) -> Path:
    value = json.dumps(report.to_dict(), sort_keys=True, indent=2) + "\n"
    identity = hashlib.sha256(value.encode("utf-8")).hexdigest()
    path = (
        Path(data_dir)
        / "reports"
        / "feature-distributions"
        / "v1"
        / f"{report.feature_set}-{report.symbol}-{identity[:16]}.json"
    )
    if path.exists():
        if path.read_text(encoding="utf-8") != value:
            raise FeatureDistributionError(f"immutable report collision: {path}")
        return path
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    try:
        with temporary.open("x", encoding="utf-8", newline="\n") as handle:
            handle.write(value)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)
    return path


def _metric(name: str, series: pd.Series) -> FeatureDistributionMetric:
    value = series.astype(float)
    if value.empty or value.isna().any() or any(not math.isfinite(item) for item in value):
        raise FeatureDistributionError(f"feature {name!r} is empty or non-finite")
    quantiles = value.quantile([0.01, 0.05, 0.5, 0.95, 0.99])
    return FeatureDistributionMetric(
        name=name,
        count=len(value),
        minimum=float(value.min()),
        q01=float(quantiles.loc[0.01]),
        q05=float(quantiles.loc[0.05]),
        median=float(quantiles.loc[0.5]),
        q95=float(quantiles.loc[0.95]),
        q99=float(quantiles.loc[0.99]),
        maximum=float(value.max()),
        mean=float(value.mean()),
        standard_deviation=float(value.std(ddof=0)),
        zero_fraction=float((value == 0).mean()),
        unique_count=int(value.nunique()),
    )


def _manifest_set_sha256(manifests: list[FeaturePartManifest]) -> str:
    records = [
        {
            "manifest_path": item.manifest_path,
            "content_sha256": item.content_sha256,
            "rows_sha256": item.rows_sha256,
            "schema_sha256": item.schema_sha256,
        }
        for item in manifests
    ]
    encoded = json.dumps(records, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()
