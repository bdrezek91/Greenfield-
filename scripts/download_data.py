"""CLI to download and store Bybit klines.

Usage:
    python scripts/download_data.py --start 2024-01-01 --end 2024-02-01
    python scripts/download_data.py --symbol BTCUSDT --timeframe 1h \
        --start 2024-01-01 --end 2024-02-01
"""

from __future__ import annotations

import os
from pathlib import Path

import pandas as pd
import structlog
import typer

from src.data.bybit_client import BybitKlineClient
from src.data.config import load_symbol_universe
from src.data.ingest import fetch_klines
from src.data.storage import write_klines
from src.data.validate import validate_dataset

log = structlog.get_logger()
app = typer.Typer(add_completion=False)


@app.command()
def download(
    start: str = typer.Option(..., help="Start date, e.g. 2024-01-01"),
    end: str = typer.Option(..., help="End date, e.g. 2024-02-01"),
    symbol: str | None = typer.Option(None, help="Single symbol, e.g. BTCUSDT. Default: all."),
    timeframe: str | None = typer.Option(None, help="Single timeframe, e.g. 1h. Default: all."),
    data_dir: str | None = typer.Option(None, help="Defaults to $DATA_DIR or ./data"),
) -> None:
    universe = load_symbol_universe()
    if symbol is not None:
        try:
            universe.validate_symbol(symbol)
        except ValueError as exc:
            raise typer.BadParameter(str(exc), param_hint="--symbol") from exc
    if timeframe is not None:
        try:
            universe.validate_timeframe(timeframe)
        except ValueError as exc:
            raise typer.BadParameter(str(exc), param_hint="--timeframe") from exc

    symbols = [symbol] if symbol else list(universe.symbols)
    intervals = (
        {k: v for k, v in universe.timeframes.items() if v == timeframe}
        if timeframe
        else universe.timeframes
    )
    resolved_data_dir = Path(data_dir or os.environ.get("DATA_DIR", "./data"))

    start_ms = int(pd.Timestamp(start, tz="UTC").timestamp() * 1000)
    end_ms = int(pd.Timestamp(end, tz="UTC").timestamp() * 1000)

    client = BybitKlineClient()

    for sym in symbols:
        for interval, tf_label in intervals.items():
            log.info("fetching", symbol=sym, timeframe=tf_label, start=start, end=end)
            df = fetch_klines(
                client,
                category=universe.category,
                symbol=sym,
                interval=interval,
                timeframe=tf_label,
                start_ms=start_ms,
                end_ms=end_ms,
            )
            if df.empty:
                log.warning("no data returned", symbol=sym, timeframe=tf_label)
                continue

            report = validate_dataset(df, tf_label)
            if not report.is_valid:
                log.error(
                    "validation failed, not writing to disk",
                    symbol=sym,
                    timeframe=tf_label,
                    gaps=len(report.missing_candle_gaps),
                    duplicates=len(report.duplicate_timestamps),
                    anomalies=len(report.anomalous_price_timestamps),
                    non_utc=report.non_utc,
                )
                continue
            if report.zero_volume_timestamps:
                log.warning(
                    "zero-volume candles present",
                    symbol=sym,
                    timeframe=tf_label,
                    count=len(report.zero_volume_timestamps),
                )

            written = write_klines(df, resolved_data_dir)
            log.info("stored", symbol=sym, timeframe=tf_label, partitions=len(written))


if __name__ == "__main__":
    app()
