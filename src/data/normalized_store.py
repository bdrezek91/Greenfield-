"""Atomic, immutable Parquet storage for normalized Silver market rows."""

from __future__ import annotations

import hashlib
import json
import os
import re
import uuid
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq

from src.data.normalized_event import (
    NORMALIZED_EVENT_SCHEMA_VERSION,
    SUPPORTED_NORMALIZER_VERSIONS,
    NormalizedMarketEvent,
)

SILVER_LAKE_ROOT = Path("silver") / f"v{NORMALIZED_EVENT_SCHEMA_VERSION}"
SILVER_MANIFEST_VERSION = 1
_SAFE_COMPONENT = re.compile(r"^[A-Za-z0-9_.-]+$")

NORMALIZED_ARROW_SCHEMA = pa.schema(
    [
        ("schema_version", pa.int16()),
        ("normalizer_version", pa.string()),
        ("normalized_id", pa.string()),
        ("raw_event_id", pa.string()),
        ("raw_payload_sha256", pa.string()),
        ("exchange", pa.string()),
        ("market_type", pa.string()),
        ("channel", pa.string()),
        ("record_type", pa.string()),
        ("symbol", pa.string()),
        ("event_ts_ms", pa.int64()),
        ("receive_ts_ns", pa.int64()),
        ("receive_sequence", pa.int64()),
        ("connection_id", pa.string()),
        ("message_type", pa.string()),
        ("sequence", pa.int64()),
        ("update_id", pa.int64()),
        ("row_index", pa.int32()),
        ("first_update_id", pa.int64()),
        ("previous_update_id", pa.int64()),
        ("side", pa.string()),
        ("price", pa.string()),
        ("size", pa.string()),
        ("trade_id", pa.string()),
        ("tick_direction", pa.string()),
        ("is_block_trade", pa.bool_()),
        ("is_rpi_trade", pa.bool_()),
        ("book_side", pa.string()),
        ("book_action", pa.string()),
        ("metric_name", pa.string()),
        ("metric_value", pa.string()),
    ]
)


class NormalizedStoreError(RuntimeError):
    """Silver storage is corrupt, incomplete, or violates immutability."""


@dataclass(frozen=True, slots=True)
class NormalizedPartManifest:
    manifest_version: int
    normalized_schema_version: int
    normalizer_version: str
    part_path: str
    content_sha256: str
    normalized_ids_sha256: str
    source_events_sha256: str
    source_part_path: str
    row_count: int
    exchange: str
    market_type: str
    channel: str
    symbol: str
    utc_date: str
    min_event_ts_ms: int
    max_event_ts_ms: int
    min_receive_ts_ns: int
    max_receive_ts_ns: int
    created_at: str

    @property
    def manifest_path(self) -> str:
        return str(Path(self.part_path).with_suffix(".manifest.json")).replace("\\", "/")

    def to_json(self) -> str:
        return json.dumps(asdict(self), sort_keys=True, separators=(",", ":")) + "\n"

    @classmethod
    def from_json(cls, value: str) -> NormalizedPartManifest:
        data = json.loads(value)
        if not isinstance(data, dict):
            raise NormalizedStoreError("normalized manifest must be a JSON object")
        manifest = cls(**data)
        if manifest.manifest_version != SILVER_MANIFEST_VERSION:
            raise NormalizedStoreError("unsupported normalized manifest version")
        if manifest.normalized_schema_version != NORMALIZED_EVENT_SCHEMA_VERSION:
            raise NormalizedStoreError("unsupported normalized event schema version")
        if manifest.normalizer_version not in SUPPORTED_NORMALIZER_VERSIONS:
            raise NormalizedStoreError("unsupported normalizer version")
        return manifest


class AtomicNormalizedWriter:
    """Write one idempotent Silver part derived from one verified Bronze part."""

    def __init__(self, data_dir: Path, *, compression: str = "zstd") -> None:
        self.data_dir = Path(data_dir)
        self.compression = compression

    def write_source_part(
        self,
        rows: list[NormalizedMarketEvent],
        *,
        source_events_sha256: str,
        source_part_path: str,
        utc_date: str,
    ) -> NormalizedPartManifest | None:
        if not rows:
            return None
        ordered = sorted(
            rows,
            key=lambda row: (
                row.receive_ts_ns,
                row.receive_sequence,
                row.row_index,
                row.normalized_id,
            ),
        )
        identity = {(row.exchange, row.market_type, row.channel, row.symbol) for row in ordered}
        if len(identity) != 1:
            raise NormalizedStoreError("one Silver part must contain one market stream")
        ids = [row.normalized_id for row in ordered]
        if len(ids) != len(set(ids)):
            raise NormalizedStoreError("duplicate normalized IDs in source part")
        exchange, market_type, channel, symbol = next(iter(identity))
        normalizer_versions = {row.normalizer_version for row in ordered}
        if len(normalizer_versions) != 1:
            raise NormalizedStoreError("one Silver part must use one normalizer version")
        normalizer_version = next(iter(normalizer_versions))
        if normalizer_version not in SUPPORTED_NORMALIZER_VERSIONS:
            raise NormalizedStoreError("unsupported normalizer version")
        for component in (exchange, market_type, channel, symbol, utc_date):
            _validate_component(component)

        ids_sha256 = _ids_checksum(ids)
        directory = (
            self.data_dir
            / SILVER_LAKE_ROOT
            / f"normalizer={normalizer_version}"
            / f"exchange={exchange}"
            / f"market={market_type}"
            / f"channel={channel}"
            / f"symbol={symbol}"
            / f"date={utc_date}"
        )
        directory.mkdir(parents=True, exist_ok=True)
        name = f"part-{source_events_sha256[:16]}-{ids_sha256[:16]}.parquet"
        part_path = directory / name
        manifest_path = part_path.with_suffix(".manifest.json")
        if part_path.exists() or manifest_path.exists():
            return self._verify_existing(part_path, manifest_path, source_events_sha256, ids_sha256)

        table = pa.Table.from_pylist(
            [row.to_record() for row in ordered], schema=NORMALIZED_ARROW_SCHEMA
        )
        temp_path = directory / f".{name}.{uuid.uuid4().hex}.tmp"
        try:
            pq.write_table(table, temp_path, compression=self.compression)
            _fsync_file(temp_path)
            content_sha256 = _file_checksum(temp_path)
            os.replace(temp_path, part_path)
        finally:
            temp_path.unlink(missing_ok=True)

        manifest = NormalizedPartManifest(
            manifest_version=SILVER_MANIFEST_VERSION,
            normalized_schema_version=NORMALIZED_EVENT_SCHEMA_VERSION,
            normalizer_version=normalizer_version,
            part_path=part_path.relative_to(self.data_dir).as_posix(),
            content_sha256=content_sha256,
            normalized_ids_sha256=ids_sha256,
            source_events_sha256=source_events_sha256,
            source_part_path=source_part_path,
            row_count=len(ordered),
            exchange=exchange,
            market_type=market_type,
            channel=channel,
            symbol=symbol,
            utc_date=utc_date,
            min_event_ts_ms=min(row.event_ts_ms for row in ordered),
            max_event_ts_ms=max(row.event_ts_ms for row in ordered),
            min_receive_ts_ns=ordered[0].receive_ts_ns,
            max_receive_ts_ns=ordered[-1].receive_ts_ns,
            created_at=datetime.now(UTC).isoformat(timespec="seconds"),
        )
        _atomic_write_text(manifest_path, manifest.to_json())
        return manifest

    def _verify_existing(
        self,
        part_path: Path,
        manifest_path: Path,
        source_events_sha256: str,
        ids_sha256: str,
    ) -> NormalizedPartManifest:
        if not part_path.is_file() or not manifest_path.is_file():
            raise NormalizedStoreError(f"incomplete Silver part collision: {part_path}")
        manifest = NormalizedPartManifest.from_json(manifest_path.read_text(encoding="utf-8"))
        if (
            manifest.source_events_sha256 != source_events_sha256
            or manifest.normalized_ids_sha256 != ids_sha256
        ):
            raise NormalizedStoreError(f"immutable Silver part collision: {part_path}")
        verify_normalized_part(self.data_dir, manifest)
        return manifest


def discover_normalized_manifests(
    data_dir: Path,
    *,
    exchange: str | None = None,
    market_type: str | None = None,
    channel: str | None = None,
    symbol: str | None = None,
    utc_date: str | None = None,
) -> list[NormalizedPartManifest]:
    root = Path(data_dir) / SILVER_LAKE_ROOT
    if not root.exists():
        return []
    manifests = []
    for path in sorted(root.rglob("*.manifest.json")):
        manifest = NormalizedPartManifest.from_json(path.read_text(encoding="utf-8"))
        if exchange is not None and manifest.exchange != exchange:
            continue
        if market_type is not None and manifest.market_type != market_type:
            continue
        if channel is not None and manifest.channel != channel:
            continue
        if symbol is not None and manifest.symbol != symbol:
            continue
        if utc_date is not None and manifest.utc_date != utc_date:
            continue
        manifests.append(manifest)
    return manifests


def read_normalized_part(
    data_dir: Path, manifest: NormalizedPartManifest
) -> list[NormalizedMarketEvent]:
    part_path = _resolve_part(Path(data_dir), manifest.part_path)
    records = pq.ParquetFile(part_path).read().to_pylist()
    return [NormalizedMarketEvent(**record) for record in records]


def verify_normalized_part(data_dir: Path, manifest: NormalizedPartManifest) -> None:
    part_path = _resolve_part(Path(data_dir), manifest.part_path)
    if not part_path.is_file():
        raise NormalizedStoreError(f"Silver part is missing: {manifest.part_path}")
    if _file_checksum(part_path) != manifest.content_sha256:
        raise NormalizedStoreError(f"Silver checksum mismatch: {manifest.part_path}")
    rows = read_normalized_part(data_dir, manifest)
    if len(rows) != manifest.row_count:
        raise NormalizedStoreError(f"Silver row-count mismatch: {manifest.part_path}")
    if _ids_checksum([row.normalized_id for row in rows]) != manifest.normalized_ids_sha256:
        raise NormalizedStoreError(f"Silver ID checksum mismatch: {manifest.part_path}")


def _ids_checksum(ids: list[str]) -> str:
    return hashlib.sha256("\n".join(ids).encode("ascii")).hexdigest()


def _file_checksum(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _atomic_write_text(path: Path, value: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    try:
        with temp_path.open("w", encoding="utf-8", newline="\n") as handle:
            handle.write(value)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_path, path)
    finally:
        temp_path.unlink(missing_ok=True)


def _fsync_file(path: Path) -> None:
    with path.open("r+b") as handle:
        handle.flush()
        os.fsync(handle.fileno())


def _resolve_part(data_dir: Path, relative_part: str) -> Path:
    candidate = (data_dir / relative_part).resolve()
    root = data_dir.resolve()
    if candidate != root and root not in candidate.parents:
        raise NormalizedStoreError(f"Silver manifest escapes data directory: {relative_part}")
    return candidate


def _validate_component(value: str) -> None:
    if not value or not _SAFE_COMPONENT.fullmatch(value):
        raise NormalizedStoreError(f"unsafe Silver partition component: {value!r}")
