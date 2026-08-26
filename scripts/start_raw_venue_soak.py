"""Create an immutable, venue-bound Phase 3 raw collector soak marker."""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path
from typing import Annotated

import typer

from src.data.raw_soak_session import create_raw_soak_session
from src.data.raw_venue_soak import raw_venue_soak_contract

app = typer.Typer(add_completion=False)


@app.command()
def start(
    venue: Annotated[str, typer.Option(help="One supported Phase 3 venue.")],
    session_id: Annotated[str, typer.Option(help="Unique lowercase evidence session ID.")],
    source_commit: Annotated[str, typer.Option(help="Exact deployed Git SHA.")],
    venue_preflight_report: Annotated[
        Path, typer.Option(help="Fresh qualified public-transport preflight report.")
    ],
    host_preflight_report: Annotated[
        Path, typer.Option(help="Fresh qualified target-host preflight report.")
    ],
    capacity_forecast_report: Annotated[
        Path, typer.Option(help="Fresh qualified forecast for this exact venue.")
    ],
    repository_root: Annotated[Path, typer.Option()] = Path("."),
    sessions_root: Annotated[
        Path | None,
        typer.Option(help="Defaults inside DATA_DIR so the marker shares its volume."),
    ] = None,
    max_evidence_age_secs: Annotated[float, typer.Option(min=1.0)] = 900.0,
) -> None:
    try:
        contract = raw_venue_soak_contract(venue)
    except ValueError as exc:
        typer.echo(f"refusing venue soak marker: {exc}", err=True)
        raise typer.Exit(code=2) from exc

    repo = repository_root.resolve()
    observed_commit = _git(repo, "rev-parse", "HEAD")
    worktree_status = _git(repo, "status", "--porcelain")
    if observed_commit != source_commit or worktree_status != "":
        typer.echo(
            "refusing venue soak marker: repository is dirty or not at source_commit",
            err=True,
        )
        raise typer.Exit(code=2)

    data_dir = Path(os.environ.get("DATA_DIR", "./data"))
    resolved_sessions_root = sessions_root or data_dir / "health" / "soak_sessions"
    output_path = resolved_sessions_root / f"{session_id}.json"
    try:
        session = create_raw_soak_session(
            session_id=session_id,
            source_commit=source_commit,
            preflight_report_path=host_preflight_report,
            capacity_forecast_report_path=capacity_forecast_report,
            expected_data_dir=data_dir,
            config_paths=(
                repo / "configs/raw_collectors.yaml",
                repo / "docker-compose.yml",
                repo / "docker-compose.monitoring.yml",
                repo / "monitoring/prometheus/prometheus.yml",
                repo / "monitoring/prometheus/alerts.yml",
                repo / "monitoring/alertmanager/alertmanager.yml",
            ),
            output_path=output_path,
            collector_ids=contract.collector_ids,
            health_namespace=contract.health_namespace,
            venue=contract.venue,
            venue_preflight_report_path=venue_preflight_report,
            max_preflight_age_secs=max_evidence_age_secs,
            max_capacity_forecast_age_secs=max_evidence_age_secs,
            max_venue_preflight_age_secs=max_evidence_age_secs,
        )
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        typer.echo(f"refusing venue soak marker: {exc}", err=True)
        raise typer.Exit(code=2) from exc

    typer.echo(json.dumps(session.to_dict(), sort_keys=True, indent=2))
    typer.echo(f"immutable venue soak marker: {output_path}")
    services = " ".join(contract.compose_services)
    typer.echo(
        "review marker, then explicitly start only this venue with: "
        f"GREENFIELD_SOAK_ID={session.session_id} "
        f"GREENFIELD_DEPLOY_COMMIT={session.source_commit} "
        f"docker compose --profile {contract.compose_profile} up -d {services}"
    )


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
