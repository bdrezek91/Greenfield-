"""CLI: run the live Binance open-interest-history poller continuously,
meant for `docker compose run -d` like scripts/collect_long_short_ratio.py.

Public data only - no API keys, no account/order actions. Live-verified
against https://fapi.binance.com in this session - see
src/data/binance_derivatives_client.py's module docstring.

Usage:
    python scripts/collect_binance_open_interest.py --symbol BTCUSDT
"""

from __future__ import annotations

import os
from pathlib import Path

import structlog
import typer

from src.data.binance_derivatives_client import VALID_PERIODS
from src.data.binance_derivatives_collector import BinanceOpenInterestCollector
from src.data.raw_collector_config import INITIAL_V2_BINANCE_SYMBOLS

log = structlog.get_logger()
app = typer.Typer(add_completion=False)


@app.command()
def collect(
    symbol: str = typer.Option(..., help=f"One of {INITIAL_V2_BINANCE_SYMBOLS}."),
    data_dir: str | None = typer.Option(None, help="Defaults to $DATA_DIR or ./data"),
    period: str = typer.Option("5m", help=f"OI aggregation window, one of {VALID_PERIODS}."),
    poll_interval_secs: float = typer.Option(60.0, help="How often to poll the endpoint."),
) -> None:
    if symbol not in INITIAL_V2_BINANCE_SYMBOLS:
        raise typer.BadParameter(
            f"symbol must be one of {INITIAL_V2_BINANCE_SYMBOLS}", param_hint="--symbol"
        )
    if period not in VALID_PERIODS:
        raise typer.BadParameter(f"period must be one of {VALID_PERIODS}", param_hint="--period")

    resolved_data_dir = Path(data_dir or os.environ.get("DATA_DIR", "./data"))
    log.info(
        "starting binance open-interest collector",
        symbol=symbol,
        period=period,
        data_dir=str(resolved_data_dir),
        poll_interval_secs=poll_interval_secs,
    )
    collector = BinanceOpenInterestCollector(
        symbol,
        resolved_data_dir,
        period=period,
        poll_interval_secs=poll_interval_secs,
    )
    collector.run_forever()


if __name__ == "__main__":
    app()
