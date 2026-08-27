"""CLI to backfill Hyperliquid funding-rate history - the Hyperliquid
counterpart to scripts/download_funding_oi.py.

Usage:
    python scripts/download_hyperliquid_funding_history.py --coin BTC \
        --start 2024-01-01 --end 2024-02-01
"""

from __future__ import annotations

import os
from pathlib import Path

import pandas as pd
import structlog
import typer

from src.data.hyperliquid_client import HyperliquidInfoClient
from src.data.hyperliquid_funding_history import fetch_hyperliquid_funding_history
from src.data.hyperliquid_storage import write_hyperliquid_funding_history

log = structlog.get_logger()
app = typer.Typer(add_completion=False)


@app.command()
def download(
    coin: str = typer.Option(..., help="Hyperliquid coin name, e.g. BTC."),
    start: str = typer.Option(..., help="Start date, e.g. 2024-01-01"),
    end: str = typer.Option(..., help="End date, e.g. 2024-02-01"),
    data_dir: str | None = typer.Option(None, help="Defaults to $DATA_DIR or ./data"),
) -> None:
    resolved_data_dir = Path(data_dir or os.environ.get("DATA_DIR", "./data"))
    start_ms = int(pd.Timestamp(start, tz="UTC").timestamp() * 1000)
    end_ms = int(pd.Timestamp(end, tz="UTC").timestamp() * 1000)

    log.info("fetching hyperliquid funding history", coin=coin, start=start, end=end)
    client = HyperliquidInfoClient()
    df = fetch_hyperliquid_funding_history(client, coin=coin, start_ms=start_ms, end_ms=end_ms)
    written = write_hyperliquid_funding_history(df, resolved_data_dir)
    log.info("stored hyperliquid funding history", coin=coin, rows=len(df), partitions=len(written))


if __name__ == "__main__":
    app()
