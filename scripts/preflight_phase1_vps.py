"""Run the Greenfield Phase 1 soak preflight on the target Linux VPS."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Annotated

import typer

from src.data.phase1_preflight import (
    DEFAULT_MINIMUM_FREE_GIB,
    evaluate_phase1_preflight,
    gather_preflight_observations,
    write_preflight_report,
)

app = typer.Typer(add_completion=False)


@app.command()
def preflight(
    source_commit: Annotated[
        str, typer.Option(help="Exact 40-character commit intended for deployment.")
    ],
    repository_root: Annotated[
        Path, typer.Option(help="Clean Greenfield repository checkout.")
    ] = Path("."),
    data_dir: Annotated[
        Path | None, typer.Option(help="Raw data volume path; defaults to DATA_DIR.")
    ] = None,
    minimum_free_gib: Annotated[
        float, typer.Option(help="Minimum free capacity before starting the soak.")
    ] = DEFAULT_MINIMUM_FREE_GIB,
    timeout_secs: Annotated[
        float, typer.Option(help="Timeout for each network/runtime probe.")
    ] = 10.0,
    report_path: Annotated[
        Path, typer.Option(help="Atomic JSON preflight evidence output.")
    ] = Path("reports/phase1_vps_preflight.json"),
) -> None:
    repo = repository_root.resolve()
    resolved_data_dir = Path(data_dir or os.environ.get("DATA_DIR", "./data"))
    observations = gather_preflight_observations(
        repository_root=repo,
        data_dir=resolved_data_dir,
        compose_files=(repo / "docker-compose.yml", repo / "docker-compose.monitoring.yml"),
        timeout_secs=timeout_secs,
    )
    report = evaluate_phase1_preflight(
        observations,
        expected_commit=source_commit,
        minimum_free_gib=minimum_free_gib,
    )
    write_preflight_report(report_path, report)
    typer.echo(json.dumps(report.to_dict(), sort_keys=True, indent=2))
    if not report.qualified:
        raise typer.Exit(code=1)


if __name__ == "__main__":
    app()
