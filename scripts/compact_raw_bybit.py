"""Create a verified compacted mirror without deleting Bronze source parts."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Annotated

import typer

from src.data.raw_compactor import compact_raw_partition

app = typer.Typer(add_completion=False)


@app.command()
def compact(
    channel: Annotated[str, typer.Option(help="Raw channel, e.g. orderbook.")],
    symbol: Annotated[str, typer.Option(help="Configured symbol, e.g. BTCUSDT.")],
    utc_date: Annotated[str, typer.Option(help="UTC partition date YYYY-MM-DD.")],
    data_dir: Annotated[
        Path | None, typer.Option(help="Defaults to DATA_DIR or ./data.")
    ] = None,
) -> None:
    resolved_data_dir = Path(data_dir or os.environ.get("DATA_DIR", "./data"))
    report = compact_raw_partition(
        resolved_data_dir,
        exchange="bybit",
        market_type="linear",
        channel=channel,
        symbol=symbol,
        utc_date=utc_date,
    )
    typer.echo(report.to_json(), nl=False)


if __name__ == "__main__":
    app()
