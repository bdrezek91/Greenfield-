"""Materialize one closed UTC day of connection-safe L2 Gold."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

import pandas as pd
import typer

from src.features.l2_materialization import (
    materialize_daily_l2_microstructure,
    write_l2_gold_report,
)

app = typer.Typer(add_completion=False)


@app.command()
def materialize(
    utc_date: Annotated[str, typer.Option()],
    as_of: Annotated[str, typer.Option()],
    exchange: Annotated[str, typer.Option()],
    market_type: Annotated[str, typer.Option()],
    symbol: Annotated[str, typer.Option()],
    code_version: Annotated[str, typer.Option()],
    data_dir: Annotated[Path, typer.Option()] = Path("data"),
    bucket_ms: Annotated[int, typer.Option()] = 60_000,
    depth_levels: Annotated[int, typer.Option()] = 5,
    replenishment_window_updates: Annotated[int, typer.Option()] = 5,
) -> None:
    report = materialize_daily_l2_microstructure(
        data_dir,
        exchange=exchange,
        market_type=market_type,
        symbol=symbol,
        utc_date=utc_date,
        as_of=pd.Timestamp(as_of),
        code_version=code_version,
        bucket_ms=bucket_ms,
        depth_levels=depth_levels,
        replenishment_window_updates=replenishment_window_updates,
    )
    path = write_l2_gold_report(data_dir, report)
    typer.echo(
        f"qualified={report.qualified}; source_rows={report.source_row_count}; "
        f"gold_rows={report.gold_row_count}; report={path}"
    )


if __name__ == "__main__":
    app()
