"""Evaluate all Greenfield v2 Phase 1 exit evidence as one fail-closed gate."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Annotated, Any

import typer
import yaml

from src.data.phase1_acceptance import (
    evaluate_phase1_acceptance,
    write_acceptance_report,
)

app = typer.Typer(add_completion=False)


@app.command()
def check(
    source_commit: Annotated[
        str, typer.Option(help="Exact 40-character deployed Git commit SHA.")
    ],
    soak_report: Annotated[
        Path, typer.Option(help="Qualified seven-day soak JSON report.")
    ] = Path("reports/raw_collector_soak.json"),
    replay_report: Annotated[
        Path, typer.Option(help="Strict full-lake replay JSON report.")
    ] = Path("reports/raw_replay.json"),
    operational_evidence: Annotated[
        Path, typer.Option(help="Reviewed Phase 1 operational evidence YAML.")
    ] = Path("reports/phase1_operational_evidence.yaml"),
    report_path: Annotated[
        Path, typer.Option(help="Atomic acceptance report output.")
    ] = Path("reports/phase1_acceptance.json"),
) -> None:
    try:
        soak = _load_json(soak_report)
        replay = _load_json(replay_report)
        evidence = _load_yaml(operational_evidence)
    except (OSError, json.JSONDecodeError, yaml.YAMLError, ValueError) as exc:
        typer.echo(f"invalid Phase 1 evidence input: {exc}", err=True)
        raise typer.Exit(code=2) from exc
    report = evaluate_phase1_acceptance(
        soak_report=soak,
        replay_report=replay,
        operational_evidence=evidence,
        expected_commit=source_commit,
    )
    write_acceptance_report(report_path, report)
    typer.echo(json.dumps(report.to_dict(), sort_keys=True, indent=2))
    if not report.qualified:
        raise typer.Exit(code=1)


def _load_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return value


def _load_yaml(path: Path) -> dict[str, Any]:
    value = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{path} must contain a YAML mapping")
    return value


if __name__ == "__main__":
    app()
