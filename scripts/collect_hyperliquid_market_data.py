"""CLI: run the live Hyperliquid market-data poller continuously (funding/
OI/mark/oracle/mid price, cross-venue predicted funding, BBO) - the
Hyperliquid counterpart to scripts/collect_okx_open_interest.py.

Read-only research data only - no order placement, no full-depth L2
collector (see src/data/hyperliquid_collector.py's module docstring).

Usage:
    python scripts/collect_hyperliquid_market_data.py --coins BTC,ETH,SOL
"""

from __future__ import annotations

import os
from pathlib import Path

import structlog
import typer

from src.data.hyperliquid_collector import HyperliquidMarketSnapshotCollector

log = structlog.get_logger()
app = typer.Typer(add_completion=False)


@app.command()
def collect(
    coins: str = typer.Option("BTC,ETH,SOL", help="Comma-separated Hyperliquid coin names."),
    data_dir: str | None = typer.Option(None, help="Defaults to $DATA_DIR or ./data"),
    poll_interval_secs: float = typer.Option(30.0, help="How often to poll the endpoint."),
) -> None:
    coin_tuple = tuple(coin.strip() for coin in coins.split(",") if coin.strip())
    if not coin_tuple:
        raise typer.BadParameter("coins must list at least one coin", param_hint="--coins")

    resolved_data_dir = Path(data_dir or os.environ.get("DATA_DIR", "./data"))
    log.info(
        "starting hyperliquid market-data collector",
        coins=coin_tuple,
        data_dir=str(resolved_data_dir),
        poll_interval_secs=poll_interval_secs,
    )
    collector = HyperliquidMarketSnapshotCollector(
        coin_tuple,
        resolved_data_dir,
        poll_interval_secs=poll_interval_secs,
    )
    collector.run_forever()


if __name__ == "__main__":
    app()
