"""Audit one closed Binance archive month for OOS research readiness."""

from __future__ import annotations

import json
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated

import typer

from src.data.binance_archive_quality import audit_binance_archive_month

app = typer.Typer(add_completion=False)


@app.command()
def audit(
    period: Annotated[str, typer.Option(help="Closed YYYY-MM period.")],
    data_dir: Annotated[Path, typer.Option(help="Greenfield data root.")] = Path("data"),
    dataset: Annotated[str, typer.Option(help="trades or aggTrades.")] = "trades",
    frequency: Annotated[str, typer.Option(help="Gold feature frequency.")] = "1min",
    output: Annotated[Path | None, typer.Option(help="Optional immutable report path.")] = None,
) -> None:
    report = audit_binance_archive_month(
        data_dir,
        period=period,
        dataset=dataset,
        frequency=frequency,
    )
    path = output or data_dir.joinpath(
        "reports",
        "binance-public-archive",
        f"quality-{dataset}-{period}-{datetime.now(UTC).strftime('%Y%m%dT%H%M%SZ')}.json",
    )
    payload = json.dumps(report, indent=2, sort_keys=True) + "\n"
    if path.exists() and path.read_text(encoding="utf-8") != payload:
        raise RuntimeError(f"immutable quality report collision: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists():
        temp = path.with_suffix(path.suffix + ".part")
        try:
            with temp.open("w", encoding="utf-8", newline="\n") as stream:
                stream.write(payload)
                stream.flush()
                os.fsync(stream.fileno())
            temp.replace(path)
        finally:
            temp.unlink(missing_ok=True)
    typer.echo(json.dumps({"report": str(path), **report}, indent=2, sort_keys=True))
    if not report["qualified"]:
        raise typer.Exit(code=2)


if __name__ == "__main__":
    app()
