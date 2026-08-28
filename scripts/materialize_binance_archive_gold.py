"""Materialize closed-period Binance trade Silver into Gold features."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Annotated

import typer

from src.data.binance_archive_gold import materialize_binance_archive_gold

GIB = 1024**3
PRICE_TICKS = {"BTCUSDT": 0.1, "ETHUSDT": 0.01, "SOLUSDT": 0.001}
app = typer.Typer(add_completion=False)


@app.command()
def materialize(
    period: Annotated[str, typer.Option(help="Closed YYYY-MM period.")],
    data_dir: Annotated[Path, typer.Option(help="Greenfield data root.")] = Path("data"),
    symbol: Annotated[str | None, typer.Option(help="Optional BTC/ETH/SOL symbol.")] = None,
    dataset: Annotated[
        str, typer.Option(help="Normalized trades or aggTrades input.")
    ] = "trades",
    frequency: Annotated[str, typer.Option(help="Causal feature bucket.")] = "1min",
    minimum_free_gib: Annotated[
        float, typer.Option(help="Hard free-space reserve.")
    ] = 20.0,
) -> None:
    symbols = [symbol.upper()] if symbol else list(PRICE_TICKS)
    if any(value not in PRICE_TICKS for value in symbols):
        raise typer.BadParameter("symbol must be BTCUSDT, ETHUSDT, or SOLUSDT")
    if dataset not in {"trades", "aggTrades"}:
        raise typer.BadParameter("dataset must be trades or aggTrades")
    reports = []
    for value in symbols:
        output, changed, metadata = materialize_binance_archive_gold(
            data_dir=data_dir,
            symbol=value,
            period=period,
            price_tick=PRICE_TICKS[value],
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
