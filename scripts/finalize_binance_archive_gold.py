"""Finalize complete daily Binance Gold into continuous period features."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Annotated

import typer

from src.data.binance_archive_gold import finalize_binance_archive_gold_period

GIB = 1024**3
SYMBOLS = ("BTCUSDT", "ETHUSDT", "SOLUSDT")
app = typer.Typer(add_completion=False)


@app.command()
def finalize(
    period: Annotated[str, typer.Option(help="Complete YYYY-MM period.")],
    data_dir: Annotated[Path, typer.Option(help="Greenfield data root.")] = Path("data"),
    symbol: Annotated[str | None, typer.Option(help="Optional BTC/ETH/SOL symbol.")] = None,
    dataset: Annotated[str, typer.Option(help="trades or aggTrades input.")] = "trades",
    frequency: Annotated[str, typer.Option(help="Causal feature bucket.")] = "1min",
    minimum_free_gib: Annotated[float, typer.Option(help="Hard free-space reserve.")] = 20.0,
) -> None:
    symbols = [symbol.upper()] if symbol else list(SYMBOLS)
    if any(value not in SYMBOLS for value in symbols):
        raise typer.BadParameter("symbol must be BTCUSDT, ETHUSDT, or SOLUSDT")
    if dataset not in {"trades", "aggTrades"}:
        raise typer.BadParameter("dataset must be trades or aggTrades")
    reports = []
    for value in symbols:
        output, changed, metadata = finalize_binance_archive_gold_period(
            data_dir=data_dir,
            symbol=value,
            period=period,
            frequency=frequency,
            dataset=dataset,
            minimum_free_bytes=int(minimum_free_gib * GIB),
        )
        reports.append(
            {
                "symbol": value,
                "output": str(output),
                "changed": changed,
                "rows": {
                    key: evidence["row_count"]
                    for key, evidence in metadata["outputs"].items()
                },
            }
        )
    typer.echo(json.dumps(reports, indent=2, sort_keys=True))


if __name__ == "__main__":
    app()
