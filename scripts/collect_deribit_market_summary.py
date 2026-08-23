"""CLI: run the live Deribit per-currency market-summary poller
continuously, meant for `docker compose run -d` like
scripts/collect_binance_open_interest.py.

Public data only - no API keys, no account/order actions. Covers
perpetual + dated futures (--kind future) or every active option series
(--kind option, live-verified as ~998 BTC / ~886 ETH instruments this
session) in one call - see
src/data/schema_deribit_market_summary.py's module docstring for why this
replaces per-instrument WS subscriptions for dated futures/options.

Usage:
    python scripts/collect_deribit_market_summary.py --currency BTC --kind option
"""

from __future__ import annotations

import os
from pathlib import Path

import structlog
import typer

from src.data.deribit_market_summary_client import VALID_CURRENCIES, VALID_KINDS
from src.data.deribit_market_summary_collector import DeribitMarketSummaryCollector

log = structlog.get_logger()
app = typer.Typer(add_completion=False)


@app.command()
def collect(
    currency: str = typer.Option(..., help=f"One of {VALID_CURRENCIES}."),
    kind: str = typer.Option(..., help=f"One of {VALID_KINDS}."),
    data_dir: str | None = typer.Option(None, help="Defaults to $DATA_DIR or ./data"),
    poll_interval_secs: float = typer.Option(
        300.0, help="How often to poll the endpoint (default 5 minutes)."
    ),
) -> None:
    if currency not in VALID_CURRENCIES:
        raise typer.BadParameter(
            f"currency must be one of {VALID_CURRENCIES}", param_hint="--currency"
        )
    if kind not in VALID_KINDS:
        raise typer.BadParameter(f"kind must be one of {VALID_KINDS}", param_hint="--kind")

    resolved_data_dir = Path(data_dir or os.environ.get("DATA_DIR", "./data"))
    log.info(
        "starting deribit market-summary collector",
        currency=currency,
        kind=kind,
        data_dir=str(resolved_data_dir),
        poll_interval_secs=poll_interval_secs,
    )
    collector = DeribitMarketSummaryCollector(
        currency,
        kind,
        resolved_data_dir,
        poll_interval_secs=poll_interval_secs,
    )
    collector.run_forever()


if __name__ == "__main__":
    app()
