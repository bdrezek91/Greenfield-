"""Immutable point-in-time Gold feature store."""

from __future__ import annotations

import hashlib
import json
import math
import os
import re
import uuid
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

GOLD_STORE_VERSION = 1
_SAFE = re.compile(r"^[A-Za-z0-9_.-]+$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")


class FeatureStoreError(RuntimeError):
    """A Gold feature batch is non-causal, invalid, or not immutable."""


@dataclass(frozen=True, slots=True)
class FeaturePartManifest:
    manifest_version: int
    feature_store_version: int
    part_path: str
    content_sha256: str
    rows_sha256: str
    schema_sha256: str
    feature_set: str
    symbol: str
    utc_date: str
    dataset_version: str
    code_version: str
    row_count: int
    feature_columns: tuple[str, ...]
    min_feature_ts_ns: int
    max_feature_ts_ns: int
    max_source_ts_ns: int
    created_at: str

    @property
    def manifest_path(self) -> str:
        return str(Path(self.part_path).with_suffix(".manifest.json")).replace("\\", "/")

    def to_json(self) -> str:
        return json.dumps(asdict(self), sort_keys=True, separators=(",", ":")) + "\n"

    @classmethod
    def from_json(cls, value: str) -> FeaturePartManifest:
        data = json.loads(value)
        if not isinstance(data, dict):
            raise FeatureStoreError("feature manifest must be an object")
        data["feature_columns"] = tuple(data["feature_columns"])
        manifest = cls(**data)
        if manifest.manifest_version != 1 or manifest.feature_store_version != 1:
            raise FeatureStoreError("unsupported feature manifest version")
        return manifest


class FeatureStore:
    def __init__(self, data_dir: Path, *, compression: str = "zstd") -> None:
        self.data_dir = Path(data_dir)
        self.compression = compression

    def write(
        self,
        frame: pd.DataFrame,
        *,
        feature_set: str,
        symbol: str,
        dataset_version: str,
        code_version: str,
    ) -> list[FeaturePartManifest]:
        prepared, feature_columns = _prepare_frame(
            frame,
            feature_set=feature_set,
            symbol=symbol,
            dataset_version=dataset_version,
            code_version=code_version,
        )
        if prepared.empty:
            return []
        dates = prepared["timestamp"].dt.strftime("%Y-%m-%d")
        manifests = []
        for utc_date in sorted(dates.unique()):
            partition = prepared.loc[dates == utc_date].reset_index(drop=True)
            manifests.append(
                self._write_partition(
                    partition,
                    feature_columns=feature_columns,
                    feature_set=feature_set,
                    symbol=symbol,
                    utc_date=str(utc_date),
                    dataset_version=dataset_version,
                    code_version=code_version,
                )
            )
        return manifests

    def _write_partition(
        self,
        frame: pd.DataFrame,
        *,
        feature_columns: tuple[str, ...],
        feature_set: str,
        symbol: str,
        utc_date: str,
        dataset_version: str,
        code_version: str,
    ) -> FeaturePartManifest:
        rows_sha256 = _frame_checksum(frame)
        schema_sha256 = _schema_checksum(frame)
        directory = (
            self.data_dir
            / "gold"
            / f"v{GOLD_STORE_VERSION}"
            / f"feature_set={feature_set}"
            / f"symbol={symbol}"
            / f"date={utc_date}"
        )
        directory.mkdir(parents=True, exist_ok=True)
        name = f"part-{dataset_version[:16]}-{code_version[:12]}-{rows_sha256[:16]}.parquet"
        part_path = directory / name
        manifest_path = part_path.with_suffix(".manifest.json")
        if part_path.exists() or manifest_path.exists():
            return self._verify_existing(part_path, manifest_path, rows_sha256)

        temp = directory / f".{name}.{uuid.uuid4().hex}.tmp"
        table = pa.Table.from_pandas(frame, preserve_index=False)
        try:
            pq.write_table(table, temp, compression=self.compression)
            _fsync(temp)
            content_sha256 = _file_checksum(temp)
            os.replace(temp, part_path)
        finally:
            temp.unlink(missing_ok=True)
        feature_ts = frame["timestamp"].astype("int64")
        source_ts = frame["max_source_timestamp"].astype("int64")
        manifest = FeaturePartManifest(
            manifest_version=1,
            feature_store_version=GOLD_STORE_VERSION,
            part_path=part_path.relative_to(self.data_dir).as_posix(),
            content_sha256=content_sha256,
            rows_sha256=rows_sha256,
            schema_sha256=schema_sha256,
            feature_set=feature_set,
            symbol=symbol,
            utc_date=utc_date,
            dataset_version=dataset_version,
            code_version=code_version,
            row_count=len(frame),
            feature_columns=feature_columns,
            min_feature_ts_ns=int(feature_ts.min()),
            max_feature_ts_ns=int(feature_ts.max()),
            max_source_ts_ns=int(source_ts.max()),
            created_at=datetime.now(UTC).isoformat(timespec="seconds"),
        )
        _atomic_write(manifest_path, manifest.to_json())
        return manifest

    def _verify_existing(
        self, part_path: Path, manifest_path: Path, rows_sha256: str
    ) -> FeaturePartManifest:
        if not part_path.is_file() or not manifest_path.is_file():
            raise FeatureStoreError(f"incomplete Gold part collision: {part_path}")
        manifest = FeaturePartManifest.from_json(manifest_path.read_text(encoding="utf-8"))
        if manifest.rows_sha256 != rows_sha256:
            raise FeatureStoreError(f"immutable Gold part collision: {part_path}")
        verify_feature_part(self.data_dir, manifest)
        return manifest


def verify_feature_part(data_dir: Path, manifest: FeaturePartManifest) -> None:
    path = _resolve(Path(data_dir), manifest.part_path)
    if not path.is_file() or _file_checksum(path) != manifest.content_sha256:
        raise FeatureStoreError(f"Gold content checksum mismatch: {manifest.part_path}")
    frame = pq.read_table(path).to_pandas()
    if len(frame) != manifest.row_count or _frame_checksum(frame) != manifest.rows_sha256:
        raise FeatureStoreError(f"Gold row checksum mismatch: {manifest.part_path}")
    if _schema_checksum(frame) != manifest.schema_sha256:
        raise FeatureStoreError(f"Gold schema checksum mismatch: {manifest.part_path}")


def _prepare_frame(
    frame: pd.DataFrame,
    *,
    feature_set: str,
    symbol: str,
    dataset_version: str,
    code_version: str,
) -> tuple[pd.DataFrame, tuple[str, ...]]:
    for value in (feature_set, symbol, code_version):
        if not _SAFE.fullmatch(value):
            raise FeatureStoreError(f"unsafe feature identity: {value!r}")
    if not _SHA256.fullmatch(dataset_version):
        raise FeatureStoreError("dataset_version must be a SHA-256")
    required = {"timestamp", "max_source_timestamp"}
    if not required.issubset(frame.columns):
        raise FeatureStoreError("feature frame requires timestamp and max_source_timestamp")
    feature_columns = tuple(sorted(set(frame.columns) - required))
    if not feature_columns:
        raise FeatureStoreError("feature frame contains no feature columns")
    if any(not _SAFE.fullmatch(name) for name in feature_columns):
        raise FeatureStoreError("unsafe feature column name")
    value = frame[["timestamp", "max_source_timestamp", *feature_columns]].copy()
    value["timestamp"] = _utc_series(value["timestamp"], "timestamp")
    value["max_source_timestamp"] = _utc_series(
        value["max_source_timestamp"], "max_source_timestamp"
    )
    value = value.sort_values("timestamp").reset_index(drop=True)
    if value["timestamp"].duplicated().any():
        raise FeatureStoreError("duplicate feature timestamps")
    if (value["max_source_timestamp"] > value["timestamp"]).any():
        raise FeatureStoreError("future source timestamp cannot enter Gold")
    for name in feature_columns:
        if not pd.api.types.is_numeric_dtype(value[name]):
            raise FeatureStoreError(f"feature {name!r} must be numeric")
        if value[name].isna().any() or any(not math.isfinite(float(item)) for item in value[name]):
            raise FeatureStoreError(f"feature {name!r} contains null or non-finite values")
    return value, feature_columns


def _utc_series(series: pd.Series, name: str) -> pd.Series:
    value = pd.to_datetime(series, utc=False)
    if value.dt.tz is None:
        raise FeatureStoreError(f"{name} must be timezone-aware")
    return value.dt.tz_convert("UTC")


def _frame_checksum(frame: pd.DataFrame) -> str:
    records: list[dict[str, Any]] = []
    for record in frame.to_dict(orient="records"):
        records.append(
            {
                key: int(value.value) if isinstance(value, pd.Timestamp) else value
                for key, value in record.items()
            }
        )
    encoded = json.dumps(records, sort_keys=True, separators=(",", ":"), allow_nan=False)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _schema_checksum(frame: pd.DataFrame) -> str:
    value = "\n".join(f"{name}:{dtype}" for name, dtype in frame.dtypes.items())
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _file_checksum(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _atomic_write(path: Path, value: str) -> None:
    temp = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    try:
        with temp.open("w", encoding="utf-8", newline="\n") as handle:
            handle.write(value)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp, path)
    finally:
        temp.unlink(missing_ok=True)


def _fsync(path: Path) -> None:
    with path.open("r+b") as handle:
        handle.flush()
        os.fsync(handle.fileno())


def _resolve(root: Path, relative: str) -> Path:
    candidate = (root / relative).resolve()
    resolved_root = root.resolve()
    if resolved_root not in candidate.parents:
        raise FeatureStoreError("Gold manifest escapes data directory")
    return candidate
