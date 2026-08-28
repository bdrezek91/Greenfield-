"""Run the preregistered development-only Triple Barrier Labels V1 screen."""

from __future__ import annotations

import json
from pathlib import Path

import typer

from src.ml.triple_barrier_runner import (
    run_triple_barrier_screen,
    write_triple_barrier_report,
)

app = typer.Typer(add_completion=False)


@app.command()
def run(
    data_dir: str = typer.Option(..., help="Greenfield data root containing klines."),
    report_path: str = typer.Option(
        "reports/triple-barrier-labels-v1/manifest.json",
        help="Development-only result manifest.",
    ),
    trial_ledger_path: str = typer.Option(
        "reports/research/trial_ledger.jsonl",
        help="Existing append-only global Experiment Factory trial ledger.",
    ),
) -> None:
    report = run_triple_barrier_screen(
        Path(data_dir), trial_ledger_path=Path(trial_ledger_path)
    )
    write_triple_barrier_report(report, Path(report_path))
    typer.echo(json.dumps(report, indent=2, allow_nan=False))


if __name__ == "__main__":
    app()
