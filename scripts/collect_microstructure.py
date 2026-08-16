"""CLI: run the live market-microstructure collector (order book, trade
tape, liquidations) continuously, meant for `docker compose run -d` like
scripts/run_paper_session.py.

Public data only - no API keys, no account/order actions, no TRADING_MODE
gate involved (see src/data/microstructure_collector.py's module
docstring).

NOT VERIFIED IN THIS SESSION - see src/data/microstructure_collector.py's
module docstring. Validate on the VPS before relying on the collected data.

Usage:
    python scripts/collect_microstructure.py --symbol BTCUSDT
"""

from __future__ import annotations

import os
from pathlib import Path

import structlog
import typer

from src.data.config import load_symbol_universe
from src.data.microstructure_collector import MicrostructureCollector

log = structlog.get_logger()
app = typer.Typer(add_completion=False)


@app.command()
def collect(
    symbol: str = typer.Option(..., help="Single symbol, e.g. BTCUSDT."),
    data_dir: str | None = typer.Option(None, help="Defaults to $DATA_DIR or ./data"),
    flush_interval_secs: float = typer.Option(30.0, help="How often to flush buffers to disk."),
    top_n: int = typer.Option(10, help="Order book levels summed into the imbalance feature."),
) -> None:
    universe = load_symbol_universe()
    try:
        universe.validate_symbol(symbol)
    except ValueError as exc:
        raise typer.BadParameter(str(exc), param_hint="--symbol") from exc

    resolved_data_dir = Path(data_dir or os.environ.get("DATA_DIR", "./data"))
    log.info(
        "starting microstructure collector",
        symbol=symbol,
        data_dir=str(resolved_data_dir),
        flush_interval_secs=flush_interval_secs,
    )
    collector = MicrostructureCollector(
        symbol,
        resolved_data_dir,
        flush_interval_secs=flush_interval_secs,
        top_n=top_n,
    )
    collector.run_forever()


if __name__ == "__main__":
    app()
