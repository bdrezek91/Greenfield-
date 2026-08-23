"""CLI: run the live Deribit near-ATM option-ticker poller continuously,
meant for `docker compose run -d` like
scripts/collect_deribit_market_summary.py.

Public data only - no API keys, no account/order actions. Unlike the
market-summary poller (one bulk call covers every active instrument),
this fetches a bounded near-ATM subset's PER-INSTRUMENT ticker each poll
- the only Deribit endpoint that returns bid_iv/ask_iv/delta, needed for
src/features/options.py's build_option_surface_snapshot. See
src/data/deribit_option_instrument.py's module docstring for why a
bounded subset (not every active instrument) is fetched this way.

Usage:
    python scripts/collect_deribit_option_ticker.py --currency BTC
"""

from __future__ import annotations

import os
from pathlib import Path

import structlog
import typer

from src.data.deribit_market_summary_client import VALID_CURRENCIES
from src.data.deribit_option_ticker_collector import DeribitOptionTickerCollector

log = structlog.get_logger()
app = typer.Typer(add_completion=False)


@app.command()
def collect(
    currency: str = typer.Option(..., help=f"One of {VALID_CURRENCIES}."),
    data_dir: str | None = typer.Option(None, help="Defaults to $DATA_DIR or ./data"),
    expiries_count: int = typer.Option(2, help="Number of nearest expiries to cover."),
    strikes_per_side: int = typer.Option(
        5, help="Strikes nearest the underlying, per side, per expiry."
    ),
    poll_interval_secs: float = typer.Option(
        300.0, help="How often to poll (default 5 minutes)."
    ),
) -> None:
    if currency not in VALID_CURRENCIES:
        raise typer.BadParameter(
            f"currency must be one of {VALID_CURRENCIES}", param_hint="--currency"
        )
    if expiries_count <= 0:
        raise typer.BadParameter("must be positive", param_hint="--expiries-count")
    if strikes_per_side <= 0:
        raise typer.BadParameter("must be positive", param_hint="--strikes-per-side")

    resolved_data_dir = Path(data_dir or os.environ.get("DATA_DIR", "./data"))
    log.info(
        "starting deribit option-ticker collector",
        currency=currency,
        data_dir=str(resolved_data_dir),
        expiries_count=expiries_count,
        strikes_per_side=strikes_per_side,
        poll_interval_secs=poll_interval_secs,
    )
    collector = DeribitOptionTickerCollector(
        currency,
        resolved_data_dir,
        expiries_count=expiries_count,
        strikes_per_side=strikes_per_side,
        poll_interval_secs=poll_interval_secs,
    )
    collector.run_forever()


if __name__ == "__main__":
    app()
