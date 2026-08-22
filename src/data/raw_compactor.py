"""Non-destructive compaction of verified Bronze parts.

Compaction writes a separate checksummed mirror and never removes or rewrites a
source part.  Archival or retention is a later, explicit storage-policy action.
"""

from __future__ import annotations

import hashlib
import json
import os
import uuid
from collections.abc import Iterable
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path

from src.data.raw_store import (
    AtomicRawWriter,
    RawStoreError,
    discover_manifests,
    read_raw_part,
    verify_raw_part,
)


@dataclass(frozen=True, slots=True)
class RawCompactionReport:
    schema_version: int
    exchange: str
    market_type: str
    channel: str
    symbol: str
    utc_date: str
    source_part_count: int
    source_row_count: int
    source_events_sha256: str
    source_parts: tuple[str, ...]
    compacted_root: str
    compacted_parts: tuple[str, ...]
    compacted_row_count: int
    compacted_events_sha256: str
    created_at: str

    def to_json(self) -> str:
        return json.dumps(asdict(self), sort_keys=True, indent=2) + "\n"


def compact_raw_partition(
    data_dir: Path,
    *,
    exchange: str,
    market_type: str,
    channel: str,
    symbol: str,
    utc_date: str,
) -> RawCompactionReport:
    data_dir = Path(data_dir)
    source_manifests = [
        manifest
        for manifest in discover_manifests(
            data_dir,
            exchange=exchange,
            market_type=market_type,
            channel=channel,
            symbol=symbol,
        )
        if manifest.utc_date == utc_date
    ]
    if not source_manifests:
        raise RawStoreError("no source raw parts match the requested partition")

    source_checksums = {}
    events = []
    seen_ids: set[str] = set()
    for manifest in source_manifests:
        verify_raw_part(data_dir, manifest)
        source_path = data_dir / manifest.part_path
        source_checksums[manifest.part_path] = _file_checksum(source_path)
        for event in read_raw_part(data_dir, manifest):
            if event.event_id in seen_ids:
                raise RawStoreError(f"duplicate source event during compaction: {event.event_id}")
            seen_ids.add(event.event_id)
            events.append(event)

    events.sort(
        key=lambda event: (event.receive_ts_ns, event.receive_sequence, event.event_id)
    )
    source_events_sha256 = _event_ids_checksum(event.event_id for event in events)
    compacted_root = data_dir / "raw_compacted"
    compacted_manifests = AtomicRawWriter(compacted_root).write(events)
    compacted_events = []
    for manifest in compacted_manifests:
        verify_raw_part(compacted_root, manifest)
        compacted_events.extend(read_raw_part(compacted_root, manifest))
    compacted_events.sort(
        key=lambda event: (event.receive_ts_ns, event.receive_sequence, event.event_id)
    )
    compacted_events_sha256 = _event_ids_checksum(
        event.event_id for event in compacted_events
    )
    if source_events_sha256 != compacted_events_sha256 or len(events) != len(
        compacted_events
    ):
        raise RawStoreError("compacted output is not event-identical to its source")

    for relative_path, checksum in source_checksums.items():
        source_path = data_dir / relative_path
        if not source_path.is_file() or _file_checksum(source_path) != checksum:
            raise RawStoreError(f"source part changed during compaction: {relative_path}")

    report = RawCompactionReport(
        schema_version=1,
        exchange=exchange,
        market_type=market_type,
        channel=channel,
        symbol=symbol,
        utc_date=utc_date,
        source_part_count=len(source_manifests),
        source_row_count=len(events),
        source_events_sha256=source_events_sha256,
        source_parts=tuple(manifest.part_path for manifest in source_manifests),
        compacted_root=compacted_root.relative_to(data_dir).as_posix(),
        compacted_parts=tuple(manifest.part_path for manifest in compacted_manifests),
        compacted_row_count=len(compacted_events),
        compacted_events_sha256=compacted_events_sha256,
        created_at=datetime.now(UTC).isoformat(timespec="seconds"),
    )
    report_path = (
        data_dir
        / "raw_compacted"
        / "reports"
        / exchange
        / market_type
        / channel
        / symbol
        / f"{utc_date}.json"
    )
    _atomic_write(report_path, report.to_json())
    return report


def _event_ids_checksum(event_ids: Iterable[str]) -> str:
    return hashlib.sha256("\n".join(event_ids).encode("ascii")).hexdigest()


def _file_checksum(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _atomic_write(path: Path, value: str) -> None:
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
