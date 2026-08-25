"""Build immutable empirical evidence from the Demo ATAS/MC decision journal."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Annotated

import typer

from src.execution.demo_signal_journal import DemoSignalJournal
from src.execution.demo_signal_validation import (
    validate_demo_signals,
    write_demo_signal_validation_report,
)

app = typer.Typer(add_completion=False)


@app.command()
def validate(
    journal_path: Annotated[Path, typer.Option()] = Path(
        "data/state/demo-scalp/signals.sqlite3"
    ),
    report_path: Annotated[Path, typer.Option()] = Path(
        "reports/demo-signal-validation.json"
    ),
    minimum_observations: Annotated[int, typer.Option(min=1)] = 1_000,
) -> None:
    report = validate_demo_signals(
        DemoSignalJournal(journal_path).entries(),
        minimum_observations=minimum_observations,
    )
    try:
        write_demo_signal_validation_report(report_path, report)
    except (OSError, ValueError) as exc:
        typer.echo(f"DEMO SIGNAL VALIDATION FAILED: {exc}", err=True)
        raise typer.Exit(code=2) from exc
    typer.echo(json.dumps(report.to_dict(), sort_keys=True, indent=2))
    if not report.qualified:
        raise typer.Exit(code=2)


if __name__ == "__main__":
    app()
