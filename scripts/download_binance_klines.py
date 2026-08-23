"""CLI to download and store Binance USDT-M futures klines - the Binance
counterpart to scripts/download_data.py, reusing
src.data.validate.validate_dataset unchanged (it operates on the generic
klines schema, not anything Bybit-specific).

Usage:
    python scripts/download_binance_klines.py --start 2024-01-01 --end 2024-02-01
    python scripts/download_binance_klines.py --symbol BTCUSDT --timeframe 1h \
        --start 2024-01-01 --end 2024-02-01
"""

from __future__ import annotations

import os
from pathlib import Path

import pandas as pd
import structlog
import typer

from src.data.binance_klines_client import BinanceKlineClient
from src.data.binance_klines_storage import write_binance_klines
from src.data.ingest_binance_klines import fetch_binance_klines
from src.data.raw_collector_config import INITIAL_V2_BINANCE_SYMBOLS
from src.data.validate import validate_dataset

log = structlog.get_logger()
app = typer.Typer(add_completion=False)

# Only the timeframes src/backtesting/data_adapter.py can turn into Bars -
# no point downloading a timeframe the backtest engine could never consume.
SUPPORTED_TIMEFRAMES: tuple[str, ...] = ("1m", "5m", "15m", "1h", "4h", "1d")


@app.command()
def download(
    start: str = typer.Option(..., help="Start date, e.g. 2024-01-01"),
    end: str = typer.Option(..., help="End date, e.g. 2024-02-01"),
    symbol: str | None = typer.Option(
        None, help=f"One of {INITIAL_V2_BINANCE_SYMBOLS}. Default: all."
    ),
    timeframe: str | None = typer.Option(
        None, help=f"One of {SUPPORTED_TIMEFRAMES}. Default: all."
    ),
    data_dir: str | None = typer.Option(None, help="Defaults to $DATA_DIR or ./data"),
) -> None:
    if symbol is not None and symbol not in INITIAL_V2_BINANCE_SYMBOLS:
        raise typer.BadParameter(
            f"symbol must be one of {INITIAL_V2_BINANCE_SYMBOLS}", param_hint="--symbol"
        )
    if timeframe is not None and timeframe not in SUPPORTED_TIMEFRAMES:
        raise typer.BadParameter(
            f"timeframe must be one of {SUPPORTED_TIMEFRAMES}", param_hint="--timeframe"
        )

    symbols = [symbol] if symbol else list(INITIAL_V2_BINANCE_SYMBOLS)
    timeframes = [timeframe] if timeframe else list(SUPPORTED_TIMEFRAMES)
    resolved_data_dir = Path(data_dir or os.environ.get("DATA_DIR", "./data"))

    start_ms = int(pd.Timestamp(start, tz="UTC").timestamp() * 1000)
    end_ms = int(pd.Timestamp(end, tz="UTC").timestamp() * 1000)

    client = BinanceKlineClient()

    for sym in symbols:
        for tf_label in timeframes:
            log.info("fetching", symbol=sym, timeframe=tf_label, start=start, end=end)
            df = fetch_binance_klines(
                client,
                symbol=sym,
                interval=tf_label,  # Binance's interval strings match our canonical labels
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

            written = write_binance_klines(df, resolved_data_dir)
            log.info("stored", symbol=sym, timeframe=tf_label, partitions=len(written))


if __name__ == "__main__":
    app()
