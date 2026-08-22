"""Create an immutable Phase 1 soak start marker after a fresh VPS preflight."""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path
from typing import Annotated

import typer

from src.data.raw_soak_session import create_raw_soak_session

app = typer.Typer(add_completion=False)


@app.command()
def start(
    session_id: Annotated[
        str, typer.Option(help="Unique lowercase evidence session ID.")
    ],
    source_commit: Annotated[
        str, typer.Option(help="Exact 40-character deployed Git commit SHA.")
    ],
    repository_root: Annotated[Path, typer.Option()] = Path("."),
    preflight_report: Annotated[Path, typer.Option()] = Path(
        "reports/phase1_vps_preflight.json"
    ),
    capacity_forecast_report: Annotated[Path, typer.Option()] = Path(
        "reports/phase1_capacity_forecast.json"
    ),
    sessions_root: Annotated[
        Path | None,
        typer.Option(help="Defaults inside DATA_DIR so the marker shares its volume."),
    ] = None,
    max_preflight_age_secs: Annotated[float, typer.Option()] = 900.0,
) -> None:
    repo = repository_root.resolve()
    observed_commit = _git(repo, "rev-parse", "HEAD")
    worktree_status = _git(repo, "status", "--porcelain")
    if observed_commit != source_commit or worktree_status != "":
        typer.echo(
            "refusing soak marker: repository is dirty or not at source_commit",
            err=True,
        )
        raise typer.Exit(code=2)
    resolved_sessions_root = sessions_root or (
        Path(os.environ.get("DATA_DIR", "./data")) / "health" / "soak_sessions"
    )
    expected_data_dir = Path(os.environ.get("DATA_DIR", "./data"))
    output_path = resolved_sessions_root / f"{session_id}.json"
    try:
        session = create_raw_soak_session(
            session_id=session_id,
            source_commit=source_commit,
            preflight_report_path=preflight_report,
            capacity_forecast_report_path=capacity_forecast_report,
            expected_data_dir=expected_data_dir,
            config_paths=(
                repo / "configs/raw_collectors.yaml",
                repo / "docker-compose.yml",
                repo / "docker-compose.monitoring.yml",
                repo / "monitoring/prometheus/prometheus.yml",
                repo / "monitoring/prometheus/alerts.yml",
                repo / "monitoring/alertmanager/alertmanager.yml",
            ),
            output_path=output_path,
            max_preflight_age_secs=max_preflight_age_secs,
        )
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        typer.echo(f"refusing soak marker: {exc}", err=True)
        raise typer.Exit(code=2) from exc
    typer.echo(json.dumps(session.to_dict(), sort_keys=True, indent=2))
    typer.echo(f"immutable soak marker: {output_path}")


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
