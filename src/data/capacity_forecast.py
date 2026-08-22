"""Fail-closed raw-lake capacity forecast from a measured collector sample."""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass
from typing import Any


@dataclass(frozen=True, slots=True)
class CapacityForecastReport:
    schema_version: int
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

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def forecast_raw_capacity(
    *,
    sample_duration_secs: float,
    sample_raw_bytes: int,
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
) -> CapacityForecastReport:
    """Project raw bytes and require lossless evidence plus stressed headroom."""

    numeric_positive = {
        "sample_duration_secs": sample_duration_secs,
        "sample_raw_bytes": sample_raw_bytes,
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
    for name, value in {
        "events_written": events_written,
        "dropped_event_count": dropped_event_count,
        "sequence_uncertainty_count": sequence_uncertainty_count,
        "sample_queue_depth": sample_queue_depth,
    }.items():
        if value < 0:
            raise ValueError(f"{name} cannot be negative")

    average_bytes_per_sec = sample_raw_bytes / sample_duration_secs
    base_projected = math.ceil(average_bytes_per_sec * target_duration_secs)
    stressed_projected = math.ceil(base_projected * burst_multiplier)
    required_capacity = stressed_projected + runtime_reserve_bytes
    checks = {
        "minimum_sample_duration": (
            sample_duration_secs >= minimum_sample_duration_secs
        ),
        "sample_fully_flushed": events_received == events_written,
        "sample_finalized": sample_finalized,
        "sample_queue_drained": sample_queue_depth == 0,
        "baseline_streams_complete": baseline_streams_complete,
        "sample_zero_drops": dropped_event_count == 0,
        "sample_zero_sequence_uncertainty": sequence_uncertainty_count == 0,
        "stressed_projection_fits_with_reserve": (
            required_capacity <= available_capacity_bytes
        ),
    }
    return CapacityForecastReport(
        schema_version=1,
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
    )
