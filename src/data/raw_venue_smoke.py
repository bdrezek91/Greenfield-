"""Immutable evidence for a short, bounded Phase 3 public-feed smoke."""

from __future__ import annotations

import hashlib
import json
import os
import re
import uuid
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from src.data.raw_venue_soak import raw_venue_soak_contract

_GIT_SHA = re.compile(r"^[0-9a-f]{40}$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")


@dataclass(frozen=True, slots=True)
class RawVenueSmokeReport:
    schema_version: int
    generated_at_utc: str
    qualified: bool
    venue: str
    health_namespace: str
    collector_id: str
    source_commit: str
    venue_preflight_report_sha256: str
    sample_root: str
    sample_duration_secs: float
    minimum_duration_secs: float
    maximum_duration_secs: float
    sample_health_sha256: str
    sample_raw_tree_sha256: str
    sample_raw_file_count: int
    sample_raw_bytes: int
    events_received: int
    events_written: int
    dropped_event_count: int
    sequence_uncertainty_count: int
    sample_queue_depth: int
    sample_finalized: bool
    baseline_streams_complete: bool
    checks: dict[str, bool]
    runtime_error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def evaluate_raw_venue_smoke(
    *,
    venue: str,
    source_commit: str,
    venue_preflight_report_sha256: str,
    sample_root: Path,
    health_path: Path,
    collector_id: str,
    minimum_duration_secs: float,
    maximum_duration_secs: float,
    runtime_error: str | None = None,
) -> RawVenueSmokeReport:
    contract = raw_venue_soak_contract(venue)
    if not _GIT_SHA.fullmatch(source_commit) or set(source_commit) == {"0"}:
        raise ValueError("source_commit must be a nonzero lowercase Git SHA")
    if not _valid_sha256(venue_preflight_report_sha256):
        raise ValueError("venue preflight hash must be a nonzero SHA-256")
    if collector_id != f"smoke-{contract.venue}":
        raise ValueError("collector_id does not match the bounded smoke identity")
    if minimum_duration_secs <= 0 or maximum_duration_secs < minimum_duration_secs:
        raise ValueError("invalid bounded smoke duration")
    resolved_root = Path(sample_root).resolve(strict=True)
    health_bytes = Path(health_path).resolve(strict=True).read_bytes()
    health = json.loads(health_bytes)
    if not isinstance(health, dict):
        raise ValueError("smoke health evidence must be a JSON object")
    started = _required_int(health, "started_ts_ns")
    ended = _required_int(health, "heartbeat_ts_ns")
    if ended <= started:
        raise ValueError("smoke health timestamps are not increasing")
    duration = (ended - started) / 1_000_000_000
    raw_tree_sha256, raw_file_count, raw_bytes = _hash_file_tree(resolved_root / "raw")
    channel_counts = health.get("channel_counts")
    expected_streams = {
        f"{channel}:{symbol}"
        for channel in contract.required_channels
        for symbol in contract.venue_symbols
    }
    streams_complete = isinstance(channel_counts, dict) and all(
        isinstance(channel_counts.get(stream), int) and channel_counts[stream] > 0
        for stream in expected_streams
    )
    events_received = _required_int(health, "events_received")
    events_written = _required_int(health, "events_written")
    dropped = _required_int(health, "dropped_event_count")
    uncertainty = _required_int(health, "sequence_uncertainty_count")
    queue_depth = _required_int(health, "queue_depth")
    finalized = health.get("status") == "stopped" and health.get("connected") is False
    checks = {
        "exact_venue": health.get("exchange") == contract.venue,
        "exact_market_type": health.get("market_type") == contract.market_type,
        "exact_health_identity": health.get("collector_id") == collector_id,
        "exact_symbol_universe": health.get("symbols") == list(contract.venue_symbols),
        "minimum_duration": duration >= minimum_duration_secs,
        "bounded_duration": duration <= maximum_duration_secs + 30.0,
        "sample_fully_flushed": events_received == events_written,
        "sample_finalized": finalized,
        "sample_queue_drained": queue_depth == 0,
        "baseline_streams_complete": streams_complete,
        "sample_zero_drops": dropped == 0,
        "sample_zero_sequence_uncertainty": uncertainty == 0,
        "raw_tree_nonempty": raw_file_count > 0 and raw_bytes > 0,
        "runtime_completed_without_error": runtime_error is None,
    }
    return RawVenueSmokeReport(
        schema_version=1,
        generated_at_utc=datetime.now(UTC).isoformat(),
        qualified=all(checks.values()),
        venue=contract.venue,
        health_namespace=contract.health_namespace,
        collector_id=collector_id,
        source_commit=source_commit,
        venue_preflight_report_sha256=venue_preflight_report_sha256,
        sample_root=str(resolved_root),
        sample_duration_secs=duration,
        minimum_duration_secs=minimum_duration_secs,
        maximum_duration_secs=maximum_duration_secs,
        sample_health_sha256=hashlib.sha256(health_bytes).hexdigest(),
        sample_raw_tree_sha256=raw_tree_sha256,
        sample_raw_file_count=raw_file_count,
        sample_raw_bytes=raw_bytes,
        events_received=events_received,
        events_written=events_written,
        dropped_event_count=dropped,
        sequence_uncertainty_count=uncertainty,
        sample_queue_depth=queue_depth,
        sample_finalized=finalized,
        baseline_streams_complete=streams_complete,
        checks=checks,
        runtime_error=runtime_error,
    )


def load_raw_venue_smoke_report(path: Path) -> RawVenueSmokeReport:
    value = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(value, dict) or value.get("schema_version") != 1:
        raise ValueError("invalid raw venue smoke report schema")
    try:
        report = RawVenueSmokeReport(
            schema_version=1,
            generated_at_utc=str(value["generated_at_utc"]),
            qualified=value["qualified"] is True,
            venue=str(value["venue"]),
            health_namespace=str(value["health_namespace"]),
            collector_id=str(value["collector_id"]),
            source_commit=str(value["source_commit"]),
            venue_preflight_report_sha256=str(value["venue_preflight_report_sha256"]),
            sample_root=str(value["sample_root"]),
            sample_duration_secs=float(value["sample_duration_secs"]),
            minimum_duration_secs=float(value["minimum_duration_secs"]),
            maximum_duration_secs=float(value["maximum_duration_secs"]),
            sample_health_sha256=str(value["sample_health_sha256"]),
            sample_raw_tree_sha256=str(value["sample_raw_tree_sha256"]),
            sample_raw_file_count=int(value["sample_raw_file_count"]),
            sample_raw_bytes=int(value["sample_raw_bytes"]),
            events_received=int(value["events_received"]),
            events_written=int(value["events_written"]),
            dropped_event_count=int(value["dropped_event_count"]),
            sequence_uncertainty_count=int(value["sequence_uncertainty_count"]),
            sample_queue_depth=int(value["sample_queue_depth"]),
            sample_finalized=value["sample_finalized"] is True,
            baseline_streams_complete=value["baseline_streams_complete"] is True,
            checks={str(key): item is True for key, item in value["checks"].items()},
            runtime_error=(
                str(value["runtime_error"]) if value.get("runtime_error") is not None else None
            ),
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError("malformed raw venue smoke report") from exc
    contract = raw_venue_soak_contract(report.venue)
    try:
        generated_at = datetime.fromisoformat(report.generated_at_utc.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError("raw venue smoke timestamp is invalid") from exc
    if generated_at.tzinfo is None:
        raise ValueError("raw venue smoke timestamp must include a timezone")
    if (
        report.health_namespace != contract.health_namespace
        or report.collector_id != f"smoke-{contract.venue}"
        or not _GIT_SHA.fullmatch(report.source_commit)
        or set(report.source_commit) == {"0"}
        or not _valid_sha256(report.venue_preflight_report_sha256)
        or not _valid_sha256(report.sample_health_sha256)
        or not _valid_sha256(report.sample_raw_tree_sha256)
        or report.sample_duration_secs < report.minimum_duration_secs
        or report.sample_duration_secs > report.maximum_duration_secs + 30.0
        or report.sample_raw_file_count <= 0
        or report.sample_raw_bytes <= 0
    ):
        raise ValueError("raw venue smoke identity mismatch")
    if not report.qualified or not report.checks or not all(report.checks.values()):
        raise ValueError("raw venue smoke report is not qualified")
    return report


def write_raw_venue_smoke_report(path: Path, report: RawVenueSmokeReport) -> None:
    document = json.dumps(report.to_dict(), sort_keys=True, indent=2) + "\n"
    _write_exclusive(Path(path), document)


def write_capacity_report_exclusive(path: Path, value: dict[str, Any]) -> None:
    document = json.dumps(value, sort_keys=True, indent=2) + "\n"
    _write_exclusive(Path(path), document)


def _hash_file_tree(root: Path) -> tuple[str, int, int]:
    resolved = Path(root).resolve(strict=True)
    if not resolved.is_dir():
        raise ValueError("sample raw path must be a directory")
    entries: list[dict[str, str | int]] = []
    total_bytes = 0
    for path in sorted(resolved.rglob("*")):
        if path.is_symlink():
            raise ValueError(f"sample raw tree cannot contain symlinks: {path}")
        if not path.is_file():
            continue
        raw = path.read_bytes()
        total_bytes += len(raw)
        entries.append(
            {
                "path": path.relative_to(resolved).as_posix(),
                "size_bytes": len(raw),
                "sha256": hashlib.sha256(raw).hexdigest(),
            }
        )
    if not entries:
        raise ValueError("sample raw tree contains no files")
    manifest = json.dumps(entries, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(manifest).hexdigest(), len(entries), total_bytes


def _required_int(value: dict[str, Any], key: str) -> int:
    item = value.get(key)
    if not isinstance(item, int) or isinstance(item, bool) or item < 0:
        raise ValueError(f"health evidence lacks nonnegative integer {key}")
    return item


def _valid_sha256(value: str) -> bool:
    return bool(_SHA256.fullmatch(value)) and set(value) != {"0"}


def _write_exclusive(path: Path, document: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    try:
        with temporary.open("x", encoding="utf-8", newline="\n") as handle:
            handle.write(document)
            handle.flush()
            os.fsync(handle.fileno())
        os.link(temporary, path)
    except FileExistsError as exc:
        raise FileExistsError(
            f"evidence already exists and will not be overwritten: {path}"
        ) from exc
    finally:
        temporary.unlink(missing_ok=True)
