"""Evidence-based audit of multi-day raw collector soak history."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True, slots=True)
class CollectorSoakResult:
    collector_id: str
    qualified: bool
    sample_count: int
    first_heartbeat_ts_ns: int | None
    last_heartbeat_ts_ns: int | None
    maximum_heartbeat_gap_secs: float | None
    reconnects_observed: int
    sequence_uncertainties_observed: int
    dropped_events_observed: int
    maximum_queue_depth: int
    errors: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class RawSoakReport:
    schema_version: int
    qualified: bool
    start_ts_ns: int
    end_ts_ns: int
    required_duration_secs: float
    maximum_heartbeat_gap_secs: float
    collectors: dict[str, CollectorSoakResult]
    session_id: str | None = None
    source_commit: str | None = None
    session_manifest_sha256: str | None = None
    health_namespace: str = "bybit-linear"
    venue: str | None = None
    venue_preflight_report_sha256: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            **asdict(self),
            "collectors": {
                collector_id: asdict(result)
                for collector_id, result in sorted(self.collectors.items())
            },
        }


def audit_raw_soak(
    data_dir: Path,
    *,
    collector_ids: tuple[str, ...],
    start_ts_ns: int,
    end_ts_ns: int,
    required_duration_secs: float = 7 * 24 * 60 * 60,
    maximum_heartbeat_gap_secs: float = 30.0,
    session_id: str | None = None,
    source_commit: str | None = None,
    session_manifest_sha256: str | None = None,
    health_namespace: str = "bybit-linear",
    venue: str | None = None,
    venue_preflight_report_sha256: str | None = None,
) -> RawSoakReport:
    if start_ts_ns >= end_ts_ns:
        raise ValueError("soak start must precede end")
    if required_duration_secs <= 0 or maximum_heartbeat_gap_secs <= 0:
        raise ValueError("soak duration and heartbeat gap must be positive")
    if not health_namespace or "/" in health_namespace or "\\" in health_namespace:
        raise ValueError("health_namespace is invalid")
    session_values = (session_id, source_commit, session_manifest_sha256)
    if any(value is not None for value in session_values) and not all(
        value is not None for value in session_values
    ):
        raise ValueError("session provenance fields must be supplied together")
    venue_values = (venue, venue_preflight_report_sha256)
    if any(value is not None for value in venue_values) and not all(
        value is not None for value in venue_values
    ):
        raise ValueError("venue provenance fields must be supplied together")
    if venue is not None and session_id is None:
        raise ValueError("venue provenance requires session provenance")
    duration_secs = (end_ts_ns - start_ts_ns) / 1_000_000_000
    results = {}
    for collector_id in collector_ids:
        snapshots = _load_history(
            Path(data_dir),
            collector_id,
            start_ts_ns=start_ts_ns,
            end_ts_ns=end_ts_ns,
            health_namespace=health_namespace,
        )
        results[collector_id] = _audit_collector(
            collector_id,
            snapshots,
            start_ts_ns=start_ts_ns,
            end_ts_ns=end_ts_ns,
            duration_secs=duration_secs,
            required_duration_secs=required_duration_secs,
            maximum_heartbeat_gap_secs=maximum_heartbeat_gap_secs,
        )
    return RawSoakReport(
        schema_version=3 if venue is not None else (2 if session_id is not None else 1),
        qualified=bool(results) and all(result.qualified for result in results.values()),
        start_ts_ns=start_ts_ns,
        end_ts_ns=end_ts_ns,
        required_duration_secs=required_duration_secs,
        maximum_heartbeat_gap_secs=maximum_heartbeat_gap_secs,
        collectors=results,
        session_id=session_id,
        source_commit=source_commit,
        session_manifest_sha256=session_manifest_sha256,
        health_namespace=health_namespace,
        venue=venue,
        venue_preflight_report_sha256=venue_preflight_report_sha256,
    )


def _load_history(
    data_dir: Path,
    collector_id: str,
    *,
    start_ts_ns: int,
    end_ts_ns: int,
    health_namespace: str,
) -> list[dict[str, Any]]:
    history_dir = data_dir / "health" / "history" / f"{health_namespace}-{collector_id}"
    by_timestamp: dict[int, dict[str, Any]] = {}
    if not history_dir.exists():
        return []
    for path in sorted(history_dir.glob("*.jsonl")):
        with path.open(encoding="utf-8") as handle:
            for line_number, line in enumerate(handle, start=1):
                if not line.strip():
                    continue
                try:
                    snapshot = json.loads(line)
                except json.JSONDecodeError as exc:
                    raise ValueError(f"invalid health history {path}:{line_number}: {exc}") from exc
                heartbeat = snapshot.get("heartbeat_ts_ns")
                if not isinstance(heartbeat, int):
                    raise ValueError(
                        f"health history lacks integer heartbeat: {path}:{line_number}"
                    )
                if start_ts_ns <= heartbeat <= end_ts_ns:
                    by_timestamp[heartbeat] = snapshot
    return [by_timestamp[timestamp] for timestamp in sorted(by_timestamp)]


def _audit_collector(
    collector_id: str,
    snapshots: list[dict[str, Any]],
    *,
    start_ts_ns: int,
    end_ts_ns: int,
    duration_secs: float,
    required_duration_secs: float,
    maximum_heartbeat_gap_secs: float,
) -> CollectorSoakResult:
    errors = []
    if duration_secs < required_duration_secs:
        errors.append(
            f"requested window is {duration_secs:.1f}s; requires {required_duration_secs:.1f}s"
        )
    if not snapshots:
        errors.append("no health-history samples in the requested window")
        return CollectorSoakResult(
            collector_id=collector_id,
            qualified=False,
            sample_count=0,
            first_heartbeat_ts_ns=None,
            last_heartbeat_ts_ns=None,
            maximum_heartbeat_gap_secs=None,
            reconnects_observed=0,
            sequence_uncertainties_observed=0,
            dropped_events_observed=0,
            maximum_queue_depth=0,
            errors=tuple(errors),
        )

    timestamps = [int(snapshot["heartbeat_ts_ns"]) for snapshot in snapshots]
    gaps = [
        (current - previous) / 1_000_000_000
        for previous, current in zip(timestamps, timestamps[1:], strict=False)
    ]
    maximum_gap = max(gaps, default=0.0)
    boundary_tolerance_ns = int(maximum_heartbeat_gap_secs * 1_000_000_000)
    if timestamps[0] > start_ts_ns + boundary_tolerance_ns:
        errors.append("health history starts too late for the requested window")
    if timestamps[-1] < end_ts_ns - boundary_tolerance_ns:
        errors.append("health history ends too early for the requested window")
    if maximum_gap > maximum_heartbeat_gap_secs:
        errors.append(
            f"maximum heartbeat gap {maximum_gap:.3f}s exceeds {maximum_heartbeat_gap_secs:.3f}s"
        )

    dropped = max(int(snapshot.get("dropped_event_count", 0)) for snapshot in snapshots)
    if dropped > 0:
        errors.append(f"collector reported {dropped} dropped events")
    bad_statuses = sorted(
        {
            str(snapshot.get("status"))
            for snapshot in snapshots
            if snapshot.get("status") in {"failed", "stopped"}
        }
    )
    if bad_statuses:
        errors.append(f"collector entered disqualifying statuses: {bad_statuses}")

    return CollectorSoakResult(
        collector_id=collector_id,
        qualified=not errors,
        sample_count=len(snapshots),
        first_heartbeat_ts_ns=timestamps[0],
        last_heartbeat_ts_ns=timestamps[-1],
        maximum_heartbeat_gap_secs=maximum_gap,
        reconnects_observed=_counter_increments(snapshots, "reconnect_count"),
        sequence_uncertainties_observed=_counter_increments(
            snapshots, "sequence_uncertainty_count"
        ),
        dropped_events_observed=dropped,
        maximum_queue_depth=max(int(snapshot.get("queue_depth", 0)) for snapshot in snapshots),
        errors=tuple(errors),
    )


def _counter_increments(snapshots: list[dict[str, Any]], name: str) -> int:
    total = 0
    previous = 0
    for snapshot in snapshots:
        current = int(snapshot.get(name, 0))
        total += current if current < previous else current - previous
        previous = current
    return total
