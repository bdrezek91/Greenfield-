"""Run one bounded, public-only OKX sample before a formal Phase 3 soak."""

from __future__ import annotations

import json
import subprocess
import threading
from pathlib import Path
from typing import Annotated

import typer

from src.data.okx_raw_collector import RawOkxCollector
from src.data.raw_collector_config import (
    DEFAULT_RAW_COLLECTOR_CONFIG,
    load_okx_raw_collector_config,
)
from src.data.raw_venue_preflight import validate_raw_venue_preflight_report
from src.data.raw_venue_smoke import (
    evaluate_raw_venue_smoke,
    write_raw_venue_smoke_report,
)

app = typer.Typer(add_completion=False)


@app.command()
def smoke(
    source_commit: Annotated[str, typer.Option(help="Exact clean deployed Git SHA.")],
    venue_preflight_report: Annotated[Path, typer.Option()],
    sample_root: Annotated[
        Path, typer.Option(help="A new dedicated directory; existing paths are refused.")
    ],
    repository_root: Annotated[Path, typer.Option()] = Path("."),
    config_path: Annotated[Path, typer.Option()] = DEFAULT_RAW_COLLECTOR_CONFIG,
    duration_secs: Annotated[float, typer.Option(min=30.0, max=900.0)] = 120.0,
    max_preflight_age_secs: Annotated[float, typer.Option(min=1.0)] = 900.0,
) -> None:
    repo = repository_root.resolve()
    if (
        _git(repo, "rev-parse", "HEAD") != source_commit
        or _git(repo, "status", "--porcelain") != ""
    ):
        typer.echo("refusing OKX smoke: repository is dirty or at the wrong commit", err=True)
        raise typer.Exit(code=2)
    try:
        preflight_sha256 = validate_raw_venue_preflight_report(
            venue_preflight_report,
            expected_commit=source_commit,
            venue="okx",
            max_age_secs=max_preflight_age_secs,
        )
        resolved_sample = sample_root.resolve()
        resolved_sample.mkdir(parents=True, exist_ok=False)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        typer.echo(f"refusing OKX smoke: {exc}", err=True)
        raise typer.Exit(code=2) from exc

    config = load_okx_raw_collector_config(config_path)
    collector_id = "smoke-okx"
    collector = RawOkxCollector(
        config.inst_ids,
        resolved_sample,
        market_type=config.market_type,
        flush_interval_secs=config.flush_interval_secs,
        max_batch_events=config.max_batch_events,
        queue_capacity=config.queue_capacity,
        ping_interval_secs=config.ping_interval_secs,
        health_interval_secs=config.health_interval_secs,
        minimum_runtime_free_gib=config.minimum_runtime_free_gib,
        reconnect_min_secs=config.reconnect_min_secs,
        reconnect_max_secs=config.reconnect_max_secs,
        collector_id=collector_id,
    )
    timer = threading.Timer(duration_secs, collector.request_stop)
    timer.daemon = True
    timer.start()
    runtime_error: str | None = None
    try:
        collector.run_forever()
    except Exception as exc:  # fail-closed operational evidence boundary
        runtime_error = f"{type(exc).__name__}: {exc}"
    finally:
        timer.cancel()

    health_path = resolved_sample / "health" / f"okx-swap-{collector_id}.json"
    report_path = resolved_sample / "okx-smoke-report.json"
    try:
        report = evaluate_raw_venue_smoke(
            venue="okx",
            source_commit=source_commit,
            venue_preflight_report_sha256=preflight_sha256,
            sample_root=resolved_sample,
            health_path=health_path,
            collector_id=collector_id,
            minimum_duration_secs=duration_secs,
            maximum_duration_secs=duration_secs,
            runtime_error=runtime_error,
        )
        write_raw_venue_smoke_report(report_path, report)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        typer.echo(f"OKX smoke evidence failed: {exc}", err=True)
        raise typer.Exit(code=1) from exc
    typer.echo(json.dumps(report.to_dict(), sort_keys=True, indent=2))
    typer.echo(f"immutable smoke report: {report_path}")
    if not report.qualified:
        raise typer.Exit(code=1)


def _git(repository_root: Path, *arguments: str) -> str | None:
    try:
        result = subprocess.run(
            ("git", *arguments),
            cwd=repository_root,
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    return result.stdout.strip() if result.returncode == 0 else None


if __name__ == "__main__":
    app()
