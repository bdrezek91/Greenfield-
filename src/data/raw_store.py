"""Atomic, immutable Parquet storage for versioned raw market events."""

from __future__ import annotations

import hashlib
import json
import os
import re
import uuid
from collections.abc import Iterator
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq

from src.data.raw_event import RAW_EVENT_SCHEMA_VERSION, RawMarketEvent

RAW_LAKE_ROOT = Path("raw") / f"v{RAW_EVENT_SCHEMA_VERSION}"
MANIFEST_VERSION = 1
_SAFE_COMPONENT = re.compile(r"^[A-Za-z0-9_.-]+$")

RAW_ARROW_SCHEMA = pa.schema(
    [
        ("schema_version", pa.int16()),
        ("ingestion_version", pa.string()),
        ("event_id", pa.string()),
        ("exchange", pa.string()),
        ("market_type", pa.string()),
        ("channel", pa.string()),
        ("topic", pa.string()),
        ("symbol", pa.string()),
        ("message_type", pa.string()),
        ("exchange_ts_ms", pa.int64()),
        ("receive_ts_ns", pa.int64()),
        ("receive_sequence", pa.int64()),
        ("matching_ts_ms", pa.int64()),
        ("sequence", pa.int64()),
        ("update_id", pa.int64()),
        ("connection_id", pa.string()),
        ("payload_sha256", pa.string()),
        ("payload_text", pa.string()),
    ]
)


class RawStoreError(RuntimeError):
    """Raw storage is incomplete, corrupt, or violates immutability."""


@dataclass(frozen=True, slots=True)
class RawPartManifest:
    manifest_version: int
    raw_schema_version: int
    part_path: str
    content_sha256: str
    events_sha256: str
    row_count: int
    exchange: str
    market_type: str
    channel: str
    symbol: str
    utc_date: str
    min_receive_ts_ns: int
    max_receive_ts_ns: int
    min_exchange_ts_ms: int | None
    max_exchange_ts_ms: int | None
    created_at: str

    @property
    def manifest_path(self) -> str:
        return str(Path(self.part_path).with_suffix(".manifest.json")).replace("\\", "/")

    def to_json(self) -> str:
        return json.dumps(asdict(self), sort_keys=True, separators=(",", ":")) + "\n"

    @classmethod
    def from_json(cls, value: str) -> RawPartManifest:
        data = json.loads(value)
        if not isinstance(data, dict):
            raise RawStoreError("raw manifest must be a JSON object")
        manifest = cls(**data)
        if manifest.manifest_version != MANIFEST_VERSION:
            raise RawStoreError(
                f"unsupported manifest version: {manifest.manifest_version}"
            )
        if manifest.raw_schema_version != RAW_EVENT_SCHEMA_VERSION:
            raise RawStoreError(
                f"unsupported raw schema version: {manifest.raw_schema_version}"
            )
        return manifest


class AtomicRawWriter:
    """Write immutable, checksummed parts grouped by Bronze partition."""

    def __init__(self, data_dir: Path, *, compression: str = "zstd") -> None:
        self.data_dir = Path(data_dir)
        self.compression = compression

    def write(self, events: list[RawMarketEvent]) -> list[RawPartManifest]:
        if not events:
            return []

        groups: dict[tuple[str, str, str, str, str], list[RawMarketEvent]] = {}
        for event in events:
            utc_date = datetime.fromtimestamp(
                event.receive_ts_ns // 1_000_000_000, tz=UTC
            ).date().isoformat()
            key = (
                event.exchange,
                event.market_type,
                event.channel,
                event.symbol,
                utc_date,
            )
            groups.setdefault(key, []).append(event)

        manifests = []
        for key in sorted(groups):
            manifests.append(self._write_partition(key, groups[key]))
        return manifests

    def _write_partition(
        self,
        key: tuple[str, str, str, str, str],
        events: list[RawMarketEvent],
    ) -> RawPartManifest:
        exchange, market_type, channel, symbol, utc_date = key
        for component in (exchange, market_type, channel, symbol, utc_date):
            _validate_component(component)

        ordered = sorted(
            events,
            key=lambda event: (
                event.receive_ts_ns,
                event.receive_sequence,
                event.event_id,
            ),
        )
        events_sha256 = _events_checksum(ordered)
        directory = (
            self.data_dir
            / RAW_LAKE_ROOT
            / f"exchange={exchange}"
            / f"market={market_type}"
            / f"channel={channel}"
            / f"symbol={symbol}"
            / f"date={utc_date}"
        )
        directory.mkdir(parents=True, exist_ok=True)
        part_name = (
            f"part-{ordered[0].receive_ts_ns}-{ordered[-1].receive_ts_ns}-"
            f"{events_sha256[:16]}.parquet"
        )
        part_path = directory / part_name
        manifest_path = part_path.with_suffix(".manifest.json")

        if part_path.exists() or manifest_path.exists():
            return self._verify_idempotent_existing(part_path, manifest_path, events_sha256)

        table = pa.Table.from_pylist(
            [event.to_record() for event in ordered], schema=RAW_ARROW_SCHEMA
        )
        temp_path = directory / f".{part_name}.{uuid.uuid4().hex}.tmp"
        try:
            pq.write_table(table, temp_path, compression=self.compression)
            _fsync_file(temp_path)
            content_sha256 = _file_checksum(temp_path)
            os.replace(temp_path, part_path)
        finally:
            temp_path.unlink(missing_ok=True)

        relative_part = part_path.relative_to(self.data_dir).as_posix()
        exchange_timestamps = [
            event.exchange_ts_ms for event in ordered if event.exchange_ts_ms is not None
        ]
        manifest = RawPartManifest(
            manifest_version=MANIFEST_VERSION,
            raw_schema_version=RAW_EVENT_SCHEMA_VERSION,
            part_path=relative_part,
            content_sha256=content_sha256,
            events_sha256=events_sha256,
            row_count=len(ordered),
            exchange=exchange,
            market_type=market_type,
            channel=channel,
            symbol=symbol,
            utc_date=utc_date,
            min_receive_ts_ns=ordered[0].receive_ts_ns,
            max_receive_ts_ns=ordered[-1].receive_ts_ns,
            min_exchange_ts_ms=min(exchange_timestamps) if exchange_timestamps else None,
            max_exchange_ts_ms=max(exchange_timestamps) if exchange_timestamps else None,
            created_at=datetime.now(UTC).isoformat(timespec="seconds"),
        )
        _atomic_write_text(manifest_path, manifest.to_json())
        return manifest

    def _verify_idempotent_existing(
        self, part_path: Path, manifest_path: Path, events_sha256: str
    ) -> RawPartManifest:
        if not part_path.is_file() or not manifest_path.is_file():
            raise RawStoreError(
                f"incomplete immutable raw part collision: {part_path.as_posix()}"
            )
        manifest = RawPartManifest.from_json(manifest_path.read_text(encoding="utf-8"))
        if manifest.events_sha256 != events_sha256:
            raise RawStoreError(f"immutable raw part collision: {part_path.as_posix()}")
        verify_raw_part(self.data_dir, manifest)
        return manifest


def discover_manifests(
    data_dir: Path,
    *,
    exchange: str | None = None,
    market_type: str | None = None,
    channel: str | None = None,
    symbol: str | None = None,
) -> list[RawPartManifest]:
    root = Path(data_dir) / RAW_LAKE_ROOT
    if not root.exists():
        return []
    manifests = []
    for path in sorted(root.rglob("*.manifest.json")):
        manifest = RawPartManifest.from_json(path.read_text(encoding="utf-8"))
        if exchange is not None and manifest.exchange != exchange:
            continue
        if market_type is not None and manifest.market_type != market_type:
            continue
        if channel is not None and manifest.channel != channel:
            continue
        if symbol is not None and manifest.symbol != symbol:
            continue
        manifests.append(manifest)
    return manifests


def load_raw_events(
    data_dir: Path,
    *,
    exchange: str | None = None,
    market_type: str | None = None,
    channel: str | None = None,
    symbol: str | None = None,
    verify: bool = True,
) -> list[RawMarketEvent]:
    return list(
        iter_raw_events(
            data_dir,
            exchange=exchange,
            market_type=market_type,
            channel=channel,
            symbol=symbol,
            verify=verify,
        )
    )


def iter_raw_events(
    data_dir: Path,
    *,
    exchange: str | None = None,
    market_type: str | None = None,
    channel: str | None = None,
    symbol: str | None = None,
    verify: bool = True,
) -> Iterator[RawMarketEvent]:
    """Stream verified parts in deterministic order without loading a lake."""
    manifests = discover_manifests(
        data_dir,
        exchange=exchange,
        market_type=market_type,
        channel=channel,
        symbol=symbol,
    )
    manifests.sort(
        key=lambda item: (
            item.exchange,
            item.market_type,
            item.channel,
            item.symbol,
            item.min_receive_ts_ns,
            item.part_path,
        )
    )
    last_key_by_stream: dict[tuple[str, str, str, str], tuple[int, int, str]] = {}
    for manifest in manifests:
        if verify:
            verify_raw_part(data_dir, manifest)
        for event in read_raw_part(data_dir, manifest):
            stream = (event.exchange, event.market_type, event.channel, event.symbol)
            order_key = (event.receive_ts_ns, event.receive_sequence, event.event_id)
            previous = last_key_by_stream.get(stream)
            if previous is not None and order_key <= previous:
                raise RawStoreError(
                    f"raw event order regressed or duplicated in stream {stream}: "
                    f"previous={previous}, observed={order_key}"
                )
            last_key_by_stream[stream] = order_key
            yield event


def read_raw_part(data_dir: Path, manifest: RawPartManifest) -> list[RawMarketEvent]:
    part_path = _resolve_part(Path(data_dir), manifest.part_path)
    table = pq.ParquetFile(part_path).read()
    return [RawMarketEvent.from_record(record) for record in table.to_pylist()]


def verify_raw_part(data_dir: Path, manifest: RawPartManifest) -> None:
    part_path = _resolve_part(Path(data_dir), manifest.part_path)
    if not part_path.is_file():
        raise RawStoreError(f"raw part is missing: {manifest.part_path}")
    if _file_checksum(part_path) != manifest.content_sha256:
        raise RawStoreError(f"raw part checksum mismatch: {manifest.part_path}")
    events = read_raw_part(data_dir, manifest)
    if len(events) != manifest.row_count:
        raise RawStoreError(f"raw part row-count mismatch: {manifest.part_path}")
    if _events_checksum(events) != manifest.events_sha256:
        raise RawStoreError(f"raw event checksum mismatch: {manifest.part_path}")


def _events_checksum(events: list[RawMarketEvent]) -> str:
    value = "\n".join(event.event_id for event in events).encode("ascii")
    return hashlib.sha256(value).hexdigest()


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
    # Windows' CRT rejects fsync on a read-only descriptor. Opening r+b is
    # portable and does not alter the already-written Parquet bytes.
    with path.open("r+b") as handle:
        handle.flush()
        os.fsync(handle.fileno())


def _resolve_part(data_dir: Path, relative_part: str) -> Path:
    candidate = (data_dir / relative_part).resolve()
    root = data_dir.resolve()
    if candidate != root and root not in candidate.parents:
        raise RawStoreError(f"raw manifest escapes data directory: {relative_part}")
    return candidate


def _validate_component(value: str) -> None:
    if not value or not _SAFE_COMPONENT.fullmatch(value):
        raise RawStoreError(f"unsafe raw partition component: {value!r}")
