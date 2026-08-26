"""Run deterministic Silver quality and catalog maintenance for one UTC day."""

from __future__ import annotations

import json
import subprocess
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Annotated

import typer

from src.data.daily_data_maintenance import (
    DailyDataMaintenanceError,
    run_daily_data_maintenance,
    write_daily_data_maintenance_report,
)
from src.data.data_quality import QualityError
from src.data.dataset_catalog import DatasetCatalogError

app = typer.Typer(add_completion=False)


@app.command()
def maintain(
    data_dir: Annotated[Path, typer.Option(help="Greenfield data root.")] = Path("data"),
    utc_date: Annotated[
        str | None,
        typer.Option(help="UTC partition day; defaults to the completed previous day."),
    ] = None,
    code_version: Annotated[
        str | None,
        typer.Option(help="Exact code version; defaults to clean Git HEAD."),
    ] = None,
    repository_root: Annotated[Path, typer.Option()] = Path("."),
) -> None:
    selected_date = utc_date or (datetime.now(UTC).date() - timedelta(days=1)).isoformat()
    repo = repository_root.resolve()
    observed_head = _git(repo, "rev-parse", "HEAD")
    selected_version = code_version or observed_head
    if (
        observed_head is None
        or selected_version != observed_head
        or _git(repo, "status", "--porcelain") != ""
    ):
        typer.echo(
            "daily maintenance requires a clean checkout at the exact code version",
            err=True,
        )
        raise typer.Exit(code=2)
    try:
        report = run_daily_data_maintenance(
            data_dir,
            utc_date=selected_date,
            code_version=selected_version,
        )
        report_path = write_daily_data_maintenance_report(data_dir, report)
    except (
        OSError,
        ValueError,
        QualityError,
        DatasetCatalogError,
        DailyDataMaintenanceError,
    ) as exc:
        typer.echo(f"daily data maintenance failed: {exc}", err=True)
        raise typer.Exit(code=2) from exc
    typer.echo(json.dumps(report.to_dict(), sort_keys=True, indent=2))
    typer.echo(f"immutable maintenance report: {report_path}")
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
