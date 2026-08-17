"""CLI: run the live long/short account-ratio poller continuously, meant
for `docker compose run -d` like scripts/collect_microstructure.py.

Public data only - no API keys, no account/order actions.

NOT VERIFIED IN THIS SESSION - see src/data/long_short_ratio_client.py's
module docstring. Validate on the VPS before relying on the collected
data or its column mapping.

Usage:
    python scripts/collect_long_short_ratio.py --symbol BTCUSDT
"""

from __future__ import annotations

import os
from pathlib import Path

import structlog
import typer

from src.data.config import load_symbol_universe
from src.data.long_short_ratio_client import VALID_PERIODS
from src.data.long_short_ratio_collector import LongShortRatioCollector

log = structlog.get_logger()
app = typer.Typer(add_completion=False)


@app.command()
def collect(
    symbol: str = typer.Option(..., help="Single symbol, e.g. BTCUSDT."),
    data_dir: str | None = typer.Option(None, help="Defaults to $DATA_DIR or ./data"),
    category: str = typer.Option("linear", help="Bybit product category."),
    period: str = typer.Option("5min", help=f"Ratio aggregation window, one of {VALID_PERIODS}."),
    poll_interval_secs: float = typer.Option(60.0, help="How often to poll the endpoint."),
) -> None:
    universe = load_symbol_universe()
    try:
        universe.validate_symbol(symbol)
    except ValueError as exc:
        raise typer.BadParameter(str(exc), param_hint="--symbol") from exc
    if period not in VALID_PERIODS:
        raise typer.BadParameter(f"period must be one of {VALID_PERIODS}", param_hint="--period")

    resolved_data_dir = Path(data_dir or os.environ.get("DATA_DIR", "./data"))
    log.info(
        "starting long/short ratio collector",
        symbol=symbol,
        period=period,
        data_dir=str(resolved_data_dir),
        poll_interval_secs=poll_interval_secs,
    )
    collector = LongShortRatioCollector(
        symbol,
        resolved_data_dir,
        category=category,
        period=period,
        poll_interval_secs=poll_interval_secs,
    )
    collector.run_forever()


if __name__ == "__main__":
    app()
