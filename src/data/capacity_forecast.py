"""Fail-closed raw-lake capacity forecast from a measured collector sample."""

from __future__ import annotations

import math
import re
from dataclasses import asdict, dataclass
from datetime import datetime
from typing import Any

_GIT_SHA = re.compile(r"^[0-9a-f]{40}$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")


@dataclass(frozen=True, slots=True)
class CapacityForecastReport:
    schema_version: int
    generated_at_utc: str
    source_commit: str
    target_data_dir: str
    sample_health_sha256: str
    sample_raw_tree_sha256: str
    sample_raw_file_count: int
    qualified: bool
    sample_duration_secs: float
    minimum_sample_duration_secs: float
    sample_raw_bytes: int
    events_received: int
    events_written: int
    dropped_event_count: int
    sequence_uncertainty_count: int
    sample_finalized: bool
    sample_queue_depth: int
    baseline_streams_complete: bool
    target_duration_secs: float
    burst_multiplier: float
    average_raw_bytes_per_sec: float
    base_projected_bytes: int
    stressed_projected_bytes: int
    runtime_reserve_bytes: int
    required_capacity_bytes: int
    available_capacity_bytes: int
    projected_headroom_bytes: int
    checks: dict[str, bool]
    venue: str | None = None
    health_namespace: str | None = None
    sample_collector_ids: tuple[str, ...] = ()
    smoke_report_sha256: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def forecast_raw_capacity(
    *,
    sample_duration_secs: float,
    sample_raw_bytes: int,
    generated_at_utc: str,
    source_commit: str,
    target_data_dir: str,
    sample_health_sha256: str,
    sample_raw_tree_sha256: str,
    sample_raw_file_count: int,
    events_received: int,
    events_written: int,
    dropped_event_count: int,
    sequence_uncertainty_count: int,
    sample_finalized: bool,
    sample_queue_depth: int,
    baseline_streams_complete: bool,
    available_capacity_bytes: int,
    target_duration_secs: float = 7 * 24 * 60 * 60,
    burst_multiplier: float = 4.0,
    runtime_reserve_bytes: int = 5 * 1024**3,
    minimum_sample_duration_secs: float = 10.0,
    venue: str | None = None,
    health_namespace: str | None = None,
    sample_collector_ids: tuple[str, ...] = (),
    smoke_report_sha256: str | None = None,
) -> CapacityForecastReport:
    """Project raw bytes and require lossless evidence plus stressed headroom."""

    numeric_positive = {
        "sample_duration_secs": sample_duration_secs,
        "sample_raw_bytes": sample_raw_bytes,
        "sample_raw_file_count": sample_raw_file_count,
        "events_received": events_received,
        "available_capacity_bytes": available_capacity_bytes,
        "target_duration_secs": target_duration_secs,
        "burst_multiplier": burst_multiplier,
        "runtime_reserve_bytes": runtime_reserve_bytes,
        "minimum_sample_duration_secs": minimum_sample_duration_secs,
    }
    invalid = [name for name, value in numeric_positive.items() if value <= 0]
    if invalid:
        raise ValueError(f"capacity forecast values must be positive: {invalid}")
    try:
        generated_at = datetime.fromisoformat(generated_at_utc.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError("generated_at_utc is invalid") from exc
    if generated_at.tzinfo is None:
        raise ValueError("generated_at_utc must include a timezone")
    if not _GIT_SHA.fullmatch(source_commit) or set(source_commit) == {"0"}:
        raise ValueError("source_commit must be a nonzero lowercase Git SHA")
    if not target_data_dir.strip():
        raise ValueError("target_data_dir is required")
    for name, hash_value in {
        "sample_health_sha256": sample_health_sha256,
        "sample_raw_tree_sha256": sample_raw_tree_sha256,
    }.items():
        if not _SHA256.fullmatch(hash_value) or set(hash_value) == {"0"}:
            raise ValueError(f"{name} must be a nonzero lowercase SHA-256")
    for name, counter_value in {
        "events_written": events_written,
        "dropped_event_count": dropped_event_count,
        "sequence_uncertainty_count": sequence_uncertainty_count,
        "sample_queue_depth": sample_queue_depth,
    }.items():
        if counter_value < 0:
            raise ValueError(f"{name} cannot be negative")
    identity_values = (venue, health_namespace)
    if any(value is not None for value in identity_values) and not all(
        value is not None for value in identity_values
    ):
        raise ValueError("venue and health_namespace must be supplied together")
    if venue is not None:
        if not venue.strip() or not health_namespace or not health_namespace.strip():
            raise ValueError("venue capacity identity cannot be blank")
        if not sample_collector_ids or len(set(sample_collector_ids)) != len(sample_collector_ids):
            raise ValueError("venue capacity sample_collector_ids must be nonempty and unique")
        if (
            smoke_report_sha256 is None
            or not _SHA256.fullmatch(smoke_report_sha256)
            or set(smoke_report_sha256) == {"0"}
        ):
            raise ValueError("venue capacity smoke_report_sha256 must be a nonzero SHA-256")
    elif sample_collector_ids:
        raise ValueError("sample_collector_ids require a venue capacity identity")
    elif smoke_report_sha256 is not None:
        raise ValueError("smoke_report_sha256 requires a venue capacity identity")

    average_bytes_per_sec = sample_raw_bytes / sample_duration_secs
    base_projected = math.ceil(average_bytes_per_sec * target_duration_secs)
    stressed_projected = math.ceil(base_projected * burst_multiplier)
    required_capacity = stressed_projected + runtime_reserve_bytes
    checks = {
        "minimum_sample_duration": (sample_duration_secs >= minimum_sample_duration_secs),
        "sample_fully_flushed": events_received == events_written,
        "sample_finalized": sample_finalized,
        "sample_queue_drained": sample_queue_depth == 0,
        "baseline_streams_complete": baseline_streams_complete,
        "sample_zero_drops": dropped_event_count == 0,
        "sample_zero_sequence_uncertainty": sequence_uncertainty_count == 0,
        "stressed_projection_fits_with_reserve": (required_capacity <= available_capacity_bytes),
    }
    return CapacityForecastReport(
        schema_version=2 if venue is not None else 1,
        generated_at_utc=generated_at_utc,
        source_commit=source_commit,
        target_data_dir=target_data_dir,
        sample_health_sha256=sample_health_sha256,
        sample_raw_tree_sha256=sample_raw_tree_sha256,
        sample_raw_file_count=sample_raw_file_count,
        qualified=all(checks.values()),
        sample_duration_secs=sample_duration_secs,
        minimum_sample_duration_secs=minimum_sample_duration_secs,
        sample_raw_bytes=sample_raw_bytes,
        events_received=events_received,
        events_written=events_written,
        dropped_event_count=dropped_event_count,
        sequence_uncertainty_count=sequence_uncertainty_count,
        sample_finalized=sample_finalized,
        sample_queue_depth=sample_queue_depth,
        baseline_streams_complete=baseline_streams_complete,
        target_duration_secs=target_duration_secs,
        burst_multiplier=burst_multiplier,
        average_raw_bytes_per_sec=average_bytes_per_sec,
        base_projected_bytes=base_projected,
        stressed_projected_bytes=stressed_projected,
        runtime_reserve_bytes=runtime_reserve_bytes,
        required_capacity_bytes=required_capacity,
        available_capacity_bytes=available_capacity_bytes,
        projected_headroom_bytes=available_capacity_bytes - required_capacity,
        checks=checks,
        venue=venue,
        health_namespace=health_namespace,
        sample_collector_ids=sample_collector_ids,
        smoke_report_sha256=smoke_report_sha256,
    )
