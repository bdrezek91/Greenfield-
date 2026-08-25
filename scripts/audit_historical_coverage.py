"""Write immutable coverage evidence for the configured historical backfill."""

from __future__ import annotations

import json
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Annotated

import typer

from src.data.historical_backfill import (
    build_historical_backfill_jobs,
    load_historical_backfill_config,
)
from src.data.historical_coverage import (
    audit_historical_coverage,
    write_historical_coverage_report,
)

app = typer.Typer(add_completion=False)


@app.command()
def audit(
    data_dir: Annotated[Path, typer.Option(help="Greenfield data root.")],
    report_path: Annotated[Path, typer.Option()],
    as_of: Annotated[str | None, typer.Option(help="UTC date; defaults to today.")] = None,
) -> None:
    selected_date = date.fromisoformat(as_of) if as_of else datetime.now(UTC).date()
    jobs = build_historical_backfill_jobs(
        load_historical_backfill_config(), as_of=selected_date
    )
    try:
        report = audit_historical_coverage(
            data_dir.resolve(), jobs, as_of=datetime.now(UTC)
        )
        write_historical_coverage_report(report_path.resolve(), report)
    except (OSError, ValueError) as exc:
        typer.echo(f"HISTORICAL COVERAGE AUDIT FAILED: {exc}", err=True)
        raise typer.Exit(code=2) from exc
    typer.echo(json.dumps(report.to_dict(), indent=2, sort_keys=True))
    if not report.qualified:
        raise typer.Exit(code=2)


if __name__ == "__main__":
    app()
