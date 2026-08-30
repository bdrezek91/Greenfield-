"""Write an immutable progress/calibration report for Bybit Demo probes."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Annotated

import typer

from src.execution.probe_calibration_report import build_probe_calibration_report

app = typer.Typer(add_completion=False)


@app.command()
def report(
    journal: Annotated[Path, typer.Option(help="Execution probe journal SQLite file.")],
    output: Annotated[Path, typer.Option(help="Output JSON path.")],
) -> None:
    payload = json.dumps(
        build_probe_calibration_report(journal), indent=2, sort_keys=True
    ) + "\n"
    output.parent.mkdir(parents=True, exist_ok=True)
    temp = output.with_suffix(output.suffix + ".part")
    try:
        with temp.open("w", encoding="utf-8", newline="\n") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        temp.replace(output)
    finally:
        temp.unlink(missing_ok=True)
    typer.echo(payload, nl=False)


if __name__ == "__main__":
    app()
