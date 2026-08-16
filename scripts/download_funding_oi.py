"""CLI to download and store Bybit funding-rate and open-interest history -
the funding/OI counterpart to scripts/download_data.py.

Usage:
    python scripts/download_funding_oi.py --symbol BTCUSDT \
        --start 2024-01-01 --end 2024-02-01

    python scripts/download_funding_oi.py --symbol BTCUSDT \
        --start 2024-01-01 --end 2024-02-01 --oi-interval 1h --only funding
"""

from __future__ import annotations

import os
from pathlib import Path

import pandas as pd
import structlog
import typer

from src.data.config import load_symbol_universe
from src.data.funding_client import BybitFundingClient
from src.data.ingest_funding import fetch_funding_rates
from src.data.ingest_open_interest import fetch_open_interest
from src.data.open_interest_client import VALID_INTERVALS, BybitOpenInterestClient
from src.data.storage import write_funding, write_open_interest

log = structlog.get_logger()
app = typer.Typer(add_completion=False)


@app.command()
def download(
    symbol: str = typer.Option(..., help="Single symbol, e.g. BTCUSDT."),
    start: str = typer.Option(..., help="Start date, e.g. 2024-01-01"),
    end: str = typer.Option(..., help="End date, e.g. 2024-02-01"),
    data_dir: str | None = typer.Option(None, help="Defaults to $DATA_DIR or ./data"),
    oi_interval: str = typer.Option(
        "1h", help=f"Open-interest aggregation window, one of {VALID_INTERVALS}."
    ),
    only: str | None = typer.Option(
        None, help="Restrict to 'funding' or 'open_interest'; default: both."
    ),
) -> None:
    universe = load_symbol_universe()
    try:
        universe.validate_symbol(symbol)
    except ValueError as exc:
        raise typer.BadParameter(str(exc), param_hint="--symbol") from exc
    if oi_interval not in VALID_INTERVALS:
        raise typer.BadParameter(
            f"oi_interval must be one of {VALID_INTERVALS}, got {oi_interval!r}",
            param_hint="--oi-interval",
        )
    if only is not None and only not in ("funding", "open_interest"):
        raise typer.BadParameter(
            f"only must be 'funding' or 'open_interest', got {only!r}", param_hint="--only"
        )

    resolved_data_dir = Path(data_dir or os.environ.get("DATA_DIR", "./data"))
    category = universe.category
    start_ms = int(pd.Timestamp(start, tz="UTC").timestamp() * 1000)
    end_ms = int(pd.Timestamp(end, tz="UTC").timestamp() * 1000)

    if only in (None, "funding"):
        log.info("fetching funding rate", symbol=symbol, start=start, end=end)
        funding_client = BybitFundingClient()
        funding_df = fetch_funding_rates(
            funding_client, category=category, symbol=symbol, start_ms=start_ms, end_ms=end_ms
        )
        written = write_funding(funding_df, resolved_data_dir)
        log.info(
            "stored funding rate", symbol=symbol, rows=len(funding_df), partitions=len(written)
        )

    if only in (None, "open_interest"):
        log.info(
            "fetching open interest", symbol=symbol, interval=oi_interval, start=start, end=end
        )
        oi_client = BybitOpenInterestClient()
        oi_df = fetch_open_interest(
            oi_client,
            category=category,
            symbol=symbol,
            interval_time=oi_interval,
            start_ms=start_ms,
            end_ms=end_ms,
        )
        written = write_open_interest(oi_df, resolved_data_dir, interval_time=oi_interval)
        log.info(
            "stored open interest",
            symbol=symbol,
            interval=oi_interval,
            rows=len(oi_df),
            partitions=len(written),
        )


if __name__ == "__main__":
    app()
