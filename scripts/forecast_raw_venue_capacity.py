"""Create a venue-bound seven-day capacity forecast from bounded smoke evidence."""

from __future__ import annotations

import hashlib
import json
import shutil
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated

import typer

from src.data.capacity_forecast import forecast_raw_capacity
from src.data.raw_venue_smoke import (
    load_raw_venue_smoke_report,
    write_capacity_report_exclusive,
)

app = typer.Typer(add_completion=False)


@app.command()
def forecast(
    smoke_report_path: Annotated[Path, typer.Option()],
    target_data_dir: Annotated[Path, typer.Option()],
    report_path: Annotated[Path, typer.Option()],
    burst_multiplier: Annotated[float, typer.Option(min=1.0)] = 4.0,
    runtime_reserve_gib: Annotated[float, typer.Option(min=1.0)] = 5.0,
    target_days: Annotated[float, typer.Option(min=7.0)] = 7.0,
) -> None:
    try:
        smoke = load_raw_venue_smoke_report(smoke_report_path)
        target = target_data_dir.resolve(strict=True)
        report = forecast_raw_capacity(
            sample_duration_secs=smoke.sample_duration_secs,
            sample_raw_bytes=smoke.sample_raw_bytes,
            generated_at_utc=datetime.now(UTC).isoformat(),
            source_commit=smoke.source_commit,
            target_data_dir=str(target),
            sample_health_sha256=smoke.sample_health_sha256,
            sample_raw_tree_sha256=smoke.sample_raw_tree_sha256,
            sample_raw_file_count=smoke.sample_raw_file_count,
            events_received=smoke.events_received,
            events_written=smoke.events_written,
            dropped_event_count=smoke.dropped_event_count,
            sequence_uncertainty_count=smoke.sequence_uncertainty_count,
            sample_finalized=smoke.sample_finalized,
            sample_queue_depth=smoke.sample_queue_depth,
            baseline_streams_complete=smoke.baseline_streams_complete,
            available_capacity_bytes=shutil.disk_usage(target).free,
            target_duration_secs=target_days * 24 * 60 * 60,
            burst_multiplier=burst_multiplier,
            runtime_reserve_bytes=int(runtime_reserve_gib * 1024**3),
            minimum_sample_duration_secs=smoke.minimum_duration_secs,
            venue=smoke.venue,
            health_namespace=smoke.health_namespace,
            sample_collector_ids=(smoke.collector_id,),
            smoke_report_sha256=hashlib.sha256(smoke_report_path.read_bytes()).hexdigest(),
        )
        write_capacity_report_exclusive(report_path, report.to_dict())
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        typer.echo(f"venue capacity forecast failed: {exc}", err=True)
        raise typer.Exit(code=2) from exc
    typer.echo(json.dumps(report.to_dict(), sort_keys=True, indent=2))
    if not report.qualified:
        raise typer.Exit(code=1)


if __name__ == "__main__":
    app()
