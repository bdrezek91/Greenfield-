"""Build immutable daily Silver quality evidence and quarantine overlays."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

import pandas as pd
import typer

from src.data.data_quality import build_daily_quality_report, write_quality_evidence

app = typer.Typer(add_completion=False)


@app.command()
def audit(
    utc_date: Annotated[str, typer.Option(help="Silver partition date, YYYY-MM-DD.")],
    data_dir: Annotated[Path, typer.Option(help="Greenfield data root.")] = Path("data"),
    observed_at: Annotated[
        str | None, typer.Option(help="UTC audit cutoff; defaults to current UTC.")
    ] = None,
) -> None:
    observed = pd.Timestamp(observed_at) if observed_at else pd.Timestamp.now(tz="UTC")
    report = build_daily_quality_report(data_dir, utc_date=utc_date, observed_at=observed)
    report_path, quarantine = write_quality_evidence(data_dir, report)
    typer.echo(
        f"qualified={report.qualified}; partitions={report.partition_count}; "
        f"quarantined={len(quarantine)}; report={report_path}"
    )
    if not report.qualified:
        raise typer.Exit(code=2)


if __name__ == "__main__":
    app()
