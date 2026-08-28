"""Run the preregistered RESEARCH-only ML Model Tournament V1."""

from __future__ import annotations

import json
from pathlib import Path

import typer

from src.ml.tournament_runner import run_tournament, write_tournament_report

app = typer.Typer(add_completion=False)


@app.command()
def run(
    data_dir: str = typer.Option(..., help="Greenfield data root containing klines."),
    report_path: str = typer.Option(
        "reports/ml-model-tournament-v1/manifest.json", help="Immutable result manifest."
    ),
    trial_ledger_path: str = typer.Option(
        "reports/research/trial_ledger.jsonl",
        help="Existing append-only global Experiment Factory trial ledger.",
    ),
) -> None:
    report = run_tournament(Path(data_dir), trial_ledger_path=Path(trial_ledger_path))
    write_tournament_report(report, Path(report_path))
    typer.echo(json.dumps(report, indent=2, allow_nan=False))


if __name__ == "__main__":
    app()
