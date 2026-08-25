"""Materialize one closed historical bar day into MC-like Gold."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

import pandas as pd
import typer

from src.features.bar_materialization import (
    materialize_daily_momentum_flow,
    write_bar_gold_report,
)

app = typer.Typer(add_completion=False)


@app.command()
def materialize(
    utc_date: Annotated[str, typer.Option(help="Closed UTC availability date.")],
    venue: Annotated[str, typer.Option(help="bybit, binance, or okx.")],
    source_symbol: Annotated[str, typer.Option(help="Exact symbol in source Parquet.")],
    symbol: Annotated[str, typer.Option(help="Canonical Gold symbol.")],
    timeframe: Annotated[str, typer.Option(help="Historical candle timeframe.")],
    as_of: Annotated[str, typer.Option(help="Timezone-aware causal cutoff.")],
    code_version: Annotated[str, typer.Option(help="Git commit for feature code.")],
    data_dir: Annotated[Path, typer.Option(help="Greenfield data root.")] = Path("data"),
    warmup_rows: Annotated[int, typer.Option(help="Prior bars retained for warmup.")] = 256,
) -> None:
    report = materialize_daily_momentum_flow(
        data_dir,
        venue=venue,
        source_symbol=source_symbol,
        symbol=symbol,
        timeframe=timeframe,
        utc_date=utc_date,
        as_of=pd.Timestamp(as_of),
        code_version=code_version,
        warmup_rows=warmup_rows,
    )
    path = write_bar_gold_report(data_dir, report)
    typer.echo(
        f"qualified={report.qualified}; source_rows={report.source_row_count}; "
        f"gold_rows={report.gold_row_count}; dataset_version={report.dataset_version}; "
        f"report={path}"
    )


if __name__ == "__main__":
    app()
