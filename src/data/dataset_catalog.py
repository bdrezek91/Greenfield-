"""Reproducible point-in-time dataset snapshots over immutable Silver parts.

`exchange`/`market_type` (Cycle 12) default to "bybit"/"linear" so every
existing caller keeps its exact prior behavior - before this cycle the
values were hardcoded, so OKX/Coinbase/Binance/Deribit Silver data (all
normalized by `src.data.normalization_pipeline.normalize_raw_lake` since
before this collector series) had no dataset-catalog/point-in-time
snapshot support at all, unlike Bybit. This was a real, undocumented gap
in "bring every exchange to the same quality contract as Bybit" - not
something deferred on purpose, just not noticed until this cycle.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import uuid
from dataclasses import asdict, dataclass
from pathlib import Path

import pandas as pd

from src.data.normalized_store import (
    discover_normalized_manifests,
    read_normalized_part,
    verify_normalized_part,
)

_VERSION = re.compile(r"^[A-Za-z0-9_.-]+$")


class DatasetCatalogError(RuntimeError):
    """A snapshot is unsafe, invalid, or collides with immutable evidence."""


@dataclass(frozen=True, slots=True)
class DatasetSnapshotPart:
    part_path: str
    content_sha256: str
    normalized_ids_sha256: str
    eligible_rows: int
    max_event_ts_ms: int
    max_receive_ts_ns: int


@dataclass(frozen=True, slots=True)
class DatasetSnapshot:
    schema_version: int
    dataset_version: str
    layer: str
    as_of_utc: str
    code_version: str
    exchange: str
    market_type: str
    symbol: str | None
    channel: str | None
    part_count: int
    eligible_row_count: int
    max_source_timestamp_ns: int
    parts: tuple[DatasetSnapshotPart, ...]

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


def build_dataset_snapshot(
    data_dir: Path,
    *,
    as_of: pd.Timestamp,
    code_version: str,
    exchange: str = "bybit",
    market_type: str = "linear",
    symbol: str | None = None,
    channel: str | None = None,
) -> DatasetSnapshot:
    cutoff = _utc_timestamp(as_of)
    if not _VERSION.fullmatch(code_version):
        raise DatasetCatalogError("code_version contains unsafe characters")
    cutoff_ms = int(cutoff.timestamp() * 1000)
    cutoff_ns = int(cutoff.timestamp() * 1_000_000_000)
    selected = []
    for manifest in discover_normalized_manifests(
        data_dir,
        exchange=exchange,
        market_type=market_type,
        symbol=symbol,
        channel=channel,
    ):
        verify_normalized_part(data_dir, manifest)
        rows = [
            row
            for row in read_normalized_part(data_dir, manifest)
            if row.event_ts_ms <= cutoff_ms and row.receive_ts_ns <= cutoff_ns
        ]
        if not rows:
            continue
        selected.append(
            DatasetSnapshotPart(
                part_path=manifest.part_path,
                content_sha256=manifest.content_sha256,
                normalized_ids_sha256=manifest.normalized_ids_sha256,
                eligible_rows=len(rows),
                max_event_ts_ms=max(row.event_ts_ms for row in rows),
                max_receive_ts_ns=max(row.receive_ts_ns for row in rows),
            )
        )
    selected.sort(key=lambda item: item.part_path)
    if not selected:
        raise DatasetCatalogError("no Silver rows are eligible at the requested as_of")
    identity = {
        "schema_version": 1,
        "layer": "silver",
        "as_of_utc": cutoff.isoformat(),
        "code_version": code_version,
        "exchange": exchange,
        "market_type": market_type,
        "symbol": symbol,
        "channel": channel,
        "parts": [asdict(item) for item in selected],
    }
    dataset_version = hashlib.sha256(
        json.dumps(identity, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    return DatasetSnapshot(
        dataset_version=dataset_version,
        part_count=len(selected),
        eligible_row_count=sum(item.eligible_rows for item in selected),
        max_source_timestamp_ns=max(
            max(item.max_event_ts_ms * 1_000_000, item.max_receive_ts_ns)
            for item in selected
        ),
        parts=tuple(selected),
        **{key: value for key, value in identity.items() if key != "parts"},
    )


def write_dataset_snapshot(data_dir: Path, snapshot: DatasetSnapshot) -> Path:
    path = Path(data_dir) / "catalog" / "v1" / f"{snapshot.dataset_version}.json"
    value = json.dumps(snapshot.to_dict(), sort_keys=True, indent=2) + "\n"
    if path.exists():
        if path.read_text(encoding="utf-8") != value:
            raise DatasetCatalogError(f"immutable dataset snapshot collision: {path}")
        return path
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
    return path


def _utc_timestamp(value: pd.Timestamp) -> pd.Timestamp:
    timestamp = pd.Timestamp(value)
    if timestamp.tzinfo is None:
        raise DatasetCatalogError("as_of must be timezone-aware")
    return timestamp.tz_convert("UTC")
