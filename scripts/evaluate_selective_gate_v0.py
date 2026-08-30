"""Evaluate the fail-closed Selective Gate v0 on immutable monthly reports."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Annotated

import typer

from src.data.binance_public_archive import sha256_file
from src.research.selective_gate_v0 import evaluate_selective_gate_v0

app = typer.Typer(add_completion=False)


@app.command()
def run(
    reports: Annotated[list[Path], typer.Option(help="Independent monthly baseline JSON.")],
    output: Annotated[Path, typer.Option(help="New immutable output report JSON.")],
    risk_veto: Annotated[bool, typer.Option(help="Force WAIT for every candidate.")] = True,
) -> None:
    payloads = tuple(json.loads(path.read_text(encoding="utf-8")) for path in reports)
    result = evaluate_selective_gate_v0(payloads, risk_veto=risk_veto)
    result["input_reports"] = [
        {"period": report["period"], "sha256": sha256_file(path)}
        for path, report in zip(reports, payloads, strict=True)
    ]
    payload = json.dumps(result, indent=2, sort_keys=True) + "\n"
    if output.exists() and output.read_text(encoding="utf-8") != payload:
        raise RuntimeError(f"immutable selective-gate report collision: {output}")
    output.parent.mkdir(parents=True, exist_ok=True)
    if not output.exists():
        temp = output.with_suffix(output.suffix + ".part")
        try:
            with temp.open("w", encoding="utf-8", newline="\n") as stream:
                stream.write(payload)
                stream.flush()
                os.fsync(stream.fileno())
            temp.replace(output)
        finally:
            temp.unlink(missing_ok=True)
    typer.echo(json.dumps({"output": str(output), **result}, indent=2, sort_keys=True))


if __name__ == "__main__":
    app()
