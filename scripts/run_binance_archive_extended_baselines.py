"""Run frozen extended baselines for one audited Binance archive month."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Annotated

import typer

from src.research.binance_archive_extended_baselines import (
    run_binance_archive_extended_baselines,
)

app = typer.Typer(add_completion=False)


@app.command()
def run(
    period: Annotated[str, typer.Option(help="Closed YYYY-MM period.")],
    data_dir: Annotated[Path, typer.Option(help="Greenfield data root.")],
    quality_report: Annotated[Path, typer.Option(help="Positive quality report.")],
    output: Annotated[Path, typer.Option(help="Immutable result JSON.")],
    preregistration: Annotated[Path, typer.Option(help="Frozen preregistration.")] = Path(
        "docs/PREREGISTRATION_BINANCE_ARCHIVE_EXTENDED_V1.md"
    ),
) -> None:
    report = run_binance_archive_extended_baselines(
        data_dir,
        period=period,
        quality_report_path=quality_report,
        preregistration_path=preregistration,
    )
    payload = json.dumps(report, indent=2, sort_keys=True) + "\n"
    if output.exists() and output.read_text(encoding="utf-8") != payload:
        raise RuntimeError(f"immutable extended baseline collision: {output}")
    output.parent.mkdir(parents=True, exist_ok=True)
    if not output.exists():
        temporary = output.with_suffix(output.suffix + ".part")
        try:
            with temporary.open("w", encoding="utf-8", newline="\n") as stream:
                stream.write(payload)
                stream.flush()
                os.fsync(stream.fileno())
            temporary.replace(output)
        finally:
            temporary.unlink(missing_ok=True)
    typer.echo(json.dumps({"report": str(output), **report}, indent=2, sort_keys=True))


if __name__ == "__main__":
    app()
