"""Create immutable public-transport evidence before a Phase 3 venue soak."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Annotated

import typer

from src.data.raw_venue_preflight import (
    SUPPORTED_VENUES,
    run_raw_venue_preflight,
    write_raw_venue_preflight_report,
)

app = typer.Typer(add_completion=False)


@app.command()
def preflight(
    source_commit: Annotated[str, typer.Option(help="Exact deployed Git SHA.")],
    venue: Annotated[
        list[str] | None,
        typer.Option(help="Repeat for selected venues; defaults to all target venues."),
    ] = None,
    repository_root: Annotated[Path, typer.Option()] = Path("."),
    report_path: Annotated[Path, typer.Option()] = Path(
        "reports/raw-venue-preflight.json"
    ),
    timeout_seconds: Annotated[float, typer.Option(min=0.1)] = 10.0,
) -> None:
    from src.data.raw_venue_preflight import probe_public_websocket

    selected = tuple(venue or SUPPORTED_VENUES)
    report = run_raw_venue_preflight(
        repository_root=repository_root,
        expected_commit=source_commit,
        venues=selected,
        probe=lambda spec: probe_public_websocket(
            spec, timeout_seconds=timeout_seconds
        ),
    )
    write_raw_venue_preflight_report(report_path, report)
    typer.echo(json.dumps(report.to_dict(), sort_keys=True, indent=2))
    if not report.qualified:
        raise typer.Exit(code=1)


if __name__ == "__main__":
    app()
