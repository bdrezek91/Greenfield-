"""Evaluate the fail-closed Selective Gate v0 on immutable monthly reports."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Annotated

import typer

from src.research.selective_gate_v0 import SelectiveGateConfig, evaluate_selective_gate_v0

app = typer.Typer(add_completion=False)


@app.command()
def run(
    reports: Annotated[list[Path], typer.Option(help="Independent monthly baseline JSON.")],
    output: Annotated[Path, typer.Option(help="Output report JSON.")],
    risk_veto: Annotated[bool, typer.Option(help="Force WAIT for every candidate.")] = False,
    execution_scenario: Annotated[str, typer.Option(help="Named execution scenario.")] = (
        "taker_taker"
    ),
    minimum_mean_net_bps: Annotated[
        float, typer.Option(help="Required mean net edge in every period.")
    ] = 3.0,
) -> None:
    payloads = tuple(json.loads(path.read_text(encoding="utf-8")) for path in reports)
    result = evaluate_selective_gate_v0(
        payloads,
        risk_veto=risk_veto,
        config=SelectiveGateConfig(
            execution_scenario=execution_scenario,
            minimum_mean_net_bps=minimum_mean_net_bps,
        ),
    )
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    typer.echo(json.dumps({"output": str(output), **result}, indent=2, sort_keys=True))


if __name__ == "__main__":
    app()
