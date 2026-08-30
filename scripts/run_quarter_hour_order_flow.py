"""Run the frozen quarter-hour opening order-flow baseline."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Annotated

import typer

from src.research.quarter_hour_order_flow import run_quarter_hour_order_flow

app = typer.Typer(add_completion=False)


@app.command()
def run(
    data_dir: Annotated[Path, typer.Option(help="Greenfield data root.")],
    quality_report: Annotated[Path, typer.Option(help="Positive immutable quality report.")],
    output: Annotated[Path, typer.Option(help="Immutable result JSON.")],
    period: Annotated[str, typer.Option(help="Closed YYYY-MM period.")],
    preregistration: Annotated[Path, typer.Option()] = Path(
        "docs/PREREGISTRATION_QUARTER_HOUR_ORDER_FLOW_V0.md"
    ),
) -> None:
    report = run_quarter_hour_order_flow(
        data_dir,
        quality_report_path=quality_report,
        preregistration_path=preregistration,
        period=period,
    )
    payload = json.dumps(report, indent=2, sort_keys=True) + "\n"
    if output.exists() and output.read_text(encoding="utf-8") != payload:
        raise RuntimeError(f"immutable baseline report collision: {output}")
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
    typer.echo(json.dumps({"report": str(output), **report}, indent=2, sort_keys=True))


if __name__ == "__main__":
    app()

