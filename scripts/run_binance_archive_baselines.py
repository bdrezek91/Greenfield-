"""Run the frozen monthly Binance archive exploratory baselines."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Annotated

import typer

from src.research.binance_archive_baselines import run_binance_archive_baselines

app = typer.Typer(add_completion=False)


@app.command()
def run(
    data_dir: Annotated[Path, typer.Option(help="Greenfield data root.")],
    quality_report: Annotated[Path, typer.Option(help="Positive immutable quality report.")],
    output: Annotated[Path, typer.Option(help="Immutable result JSON.")],
    period: Annotated[str, typer.Option(help="Closed YYYY-MM period.")] = "2026-07",
    preregistration: Annotated[Path, typer.Option(help="Frozen preregistration.")] = Path(
        "docs/PREREGISTRATION_BINANCE_ARCHIVE_BASELINES_2026_07.md"
    ),
) -> None:
    report = run_binance_archive_baselines(
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
