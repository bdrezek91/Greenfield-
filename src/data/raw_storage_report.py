"""Read-only Bronze raw-lake disk-usage and age report (Cycle 13).

Every collector already enforces its own live storage reserve
(`minimum_runtime_free_gib` - see `src.data.raw_collector_config` and each
`Raw*Collector`'s `_enforce_storage_reserve`), but that only answers "is
there enough free space to keep this one collector running." Nothing in
the repository could answer "how much disk does the whole Bronze lake
actually use, broken down by exchange/channel/date, and how old is the
oldest data" - a real, previously-missing piece of "kontrola miejsca na
dysku" (disk space control) from the master plan's data-lake section.

This module is deliberately **read-only and non-destructive**: it reports
usage and age, nothing more. Actual retention/archival (deciding what is
safe to delete and deleting it) is explicitly NOT implemented here, for
the same reason `src.data.raw_compactor`'s own docstring already gives -
"archival or retention is a later, explicit storage-policy action." A
correct retention decision needs a human-approved policy (how many days,
whether a verified compacted mirror and a passing Silver quality report
are required first, etc.) plus considerable additional safety engineering
before any deletion is safe to automate - conflating that with a
reporting tool would risk exactly the kind of rushed, under-verified
destructive capability this project's own rules warn against. This report
gives an operator (or a future, separately-reviewed retention cycle) the
visibility needed to make that policy decision; it does not make it.
"""

from __future__ import annotations

import json
import os
import uuid
from collections import defaultdict
from dataclasses import asdict, dataclass
from datetime import UTC, date, datetime
from pathlib import Path

from src.data.raw_store import RawPartManifest, discover_manifests


@dataclass(frozen=True, slots=True)
class RawStorageGroup:
    """One (exchange, market_type, channel, symbol) partition family,
    aggregated across every UTC date currently on disk for it."""

    exchange: str
    market_type: str
    channel: str
    symbol: str
    part_count: int
    row_count: int
    total_bytes: int
    oldest_utc_date: str
    newest_utc_date: str
    oldest_partition_age_days: int

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class RawStorageReport:
    schema_version: int
    generated_at_utc: str
    total_part_count: int
    total_row_count: int
    total_bytes: int
    groups: tuple[RawStorageGroup, ...]

    def to_dict(self) -> dict[str, object]:
        value = asdict(self)
        value["groups"] = [group.to_dict() for group in self.groups]
        return value


def build_raw_storage_report(
    data_dir: Path,
    *,
    now_utc: datetime,
    exchange: str | None = None,
) -> RawStorageReport:
    """Aggregate every raw manifest currently on disk. Never reads or
    modifies the underlying part files themselves - only their manifests
    (`row_count`, `part_path`) plus a `stat()` of each part file for its
    byte size, so this is safe to run against a live, actively-written
    lake (it does not need `verify_raw_part`'s full checksum re-read)."""
    if now_utc.tzinfo is None:
        raise ValueError("now_utc must be timezone-aware")
    now = now_utc.astimezone(UTC)
    data_dir = Path(data_dir)
    manifests = discover_manifests(data_dir, exchange=exchange)

    by_key: dict[tuple[str, str, str, str], list[RawPartManifest]] = defaultdict(list)
    for manifest in manifests:
        key = (manifest.exchange, manifest.market_type, manifest.channel, manifest.symbol)
        by_key[key].append(manifest)

    groups = []
    total_bytes = 0
    total_rows = 0
    for (group_exchange, market_type, channel, symbol), group_manifests in by_key.items():
        dates = sorted(m.utc_date for m in group_manifests)
        oldest_date = dates[0]
        group_bytes = sum(
            _part_size_bytes(data_dir, manifest) for manifest in group_manifests
        )
        group_rows = sum(manifest.row_count for manifest in group_manifests)
        total_bytes += group_bytes
        total_rows += group_rows
        groups.append(
            RawStorageGroup(
                exchange=group_exchange,
                market_type=market_type,
                channel=channel,
                symbol=symbol,
                part_count=len(group_manifests),
                row_count=group_rows,
                total_bytes=group_bytes,
                oldest_utc_date=oldest_date,
                newest_utc_date=dates[-1],
                oldest_partition_age_days=_age_days(oldest_date, now),
            )
        )
    groups.sort(key=lambda g: (g.exchange, g.market_type, g.channel, g.symbol))

    return RawStorageReport(
        schema_version=1,
        generated_at_utc=now.isoformat(),
        total_part_count=len(manifests),
        total_row_count=total_rows,
        total_bytes=total_bytes,
        groups=tuple(groups),
    )


def write_raw_storage_report(data_dir: Path, report: RawStorageReport) -> Path:
    """Overwrites the same path every time - unlike raw/Silver manifests
    and quality/catalog evidence, this report is a live, regenerable
    summary, not immutable evidence, so it does not need idempotent-or-
    reject collision handling."""
    path = Path(data_dir) / "reports" / "raw_storage.json"
    value = json.dumps(report.to_dict(), sort_keys=True, indent=2) + "\n"
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


def _part_size_bytes(data_dir: Path, manifest: RawPartManifest) -> int:
    path = data_dir / manifest.part_path
    try:
        return path.stat().st_size
    except OSError:
        # A manifest without its part file is a real, separate integrity
        # problem (see verify_raw_part) - this report's job is disk usage,
        # not integrity, so it counts the missing file as zero bytes
        # rather than raising and hiding every other group's numbers.
        return 0


def _age_days(utc_date: str, now: datetime) -> int:
    partition_date = date.fromisoformat(utc_date)
    return (now.date() - partition_date).days
