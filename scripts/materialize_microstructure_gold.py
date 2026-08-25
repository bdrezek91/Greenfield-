"""Materialize one closed, verified Silver trade day into immutable Gold."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

import pandas as pd
import typer

from src.features.materialization import (
    materialize_daily_trade_microstructure,
    write_gold_materialization_report,
)

app = typer.Typer(add_completion=False)


@app.command()
def materialize(
    utc_date: Annotated[str, typer.Option(help="Closed Silver UTC date, YYYY-MM-DD.")],
    symbol: Annotated[str, typer.Option(help="Exact symbol, e.g. BTCUSDT.")],
    price_tick: Annotated[str, typer.Option(help="Exact venue price increment.")],
    as_of: Annotated[str, typer.Option(help="Timezone-aware causal build cutoff.")],
    code_version: Annotated[str, typer.Option(help="Git commit for feature code.")],
    data_dir: Annotated[Path, typer.Option(help="Greenfield data root.")] = Path("data"),
    exchange: Annotated[str, typer.Option(help="Silver exchange.")] = "bybit",
    market_type: Annotated[str, typer.Option(help="Silver market type.")] = "linear",
    bucket_ms: Annotated[int, typer.Option(help="Feature bucket size in milliseconds.")] = 60_000,
    imbalance_ratio: Annotated[
        float, typer.Option(help="Diagonal footprint imbalance threshold.")
    ] = 3.0,
) -> None:
    report = materialize_daily_trade_microstructure(
        data_dir,
        exchange=exchange,
        market_type=market_type,
        symbol=symbol,
        utc_date=utc_date,
        as_of=pd.Timestamp(as_of),
        code_version=code_version,
        price_tick=price_tick,
        bucket_ms=bucket_ms,
        imbalance_ratio=imbalance_ratio,
    )
    path = write_gold_materialization_report(data_dir, report)
    typer.echo(
        f"qualified={report.qualified}; source_rows={report.source_row_count}; "
        f"gold_rows={report.gold_row_count}; dataset_version={report.dataset_version}; "
        f"report={path}"
    )


if __name__ == "__main__":
    app()
