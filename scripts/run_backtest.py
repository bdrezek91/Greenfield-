"""CLI to run a NautilusTrader backtest against locally stored Parquet klines.

No strategy is attached yet (Phase 3 scope - see docs/BACKTESTING.md and
docs/PHASE_0_ARCHITECTURE_RESEARCH.md). This proves the data/instrument/
venue/cost plumbing end to end; strategy families arrive in Phase 5+.

Usage:
    python scripts/run_backtest.py --start 2024-01-01 --end 2024-02-01
    python scripts/run_backtest.py --symbol BTCUSDT --timeframe 1h \
        --start 2024-01-01 --end 2024-02-01
"""

from __future__ import annotations

import os
from decimal import Decimal
from pathlib import Path

import pandas as pd
import structlog
import typer

from src.backtesting.engine import BacktestRunSpec, run_backtest
from src.data.config import load_symbol_universe

log = structlog.get_logger()
app = typer.Typer(add_completion=False)


@app.command()
def backtest(
    start: str = typer.Option(..., help="Start date, e.g. 2024-01-01"),
    end: str = typer.Option(..., help="End date, e.g. 2024-02-01"),
    symbol: str | None = typer.Option(None, help="Single symbol, e.g. BTCUSDT. Default: all."),
    timeframe: str = typer.Option("1h", help="Timeframe, e.g. 1h."),
    data_dir: str | None = typer.Option(None, help="Defaults to $DATA_DIR or ./data"),
    starting_balance: float = typer.Option(100_000.0, help="Starting USDT balance."),
) -> None:
    universe = load_symbol_universe()
    if symbol is not None:
        try:
            universe.validate_symbol(symbol)
        except ValueError as exc:
            raise typer.BadParameter(str(exc), param_hint="--symbol") from exc
    try:
        universe.validate_timeframe(timeframe)
    except ValueError as exc:
        raise typer.BadParameter(str(exc), param_hint="--timeframe") from exc

    symbols = [symbol] if symbol else list(universe.symbols)
    resolved_data_dir = Path(data_dir or os.environ.get("DATA_DIR", "./data"))

    spec = BacktestRunSpec(
        symbols=symbols,
        timeframe=timeframe,
        start=pd.Timestamp(start, tz="UTC"),
        end=pd.Timestamp(end, tz="UTC"),
        data_dir=resolved_data_dir,
        starting_balance=Decimal(str(starting_balance)),
    )

    log.info("running backtest", symbols=symbols, timeframe=timeframe, start=start, end=end)
    engine = run_backtest(spec)

    venue = next(iter(engine.list_venues()))
    account_report = engine.trader.generate_account_report(venue)
    positions_report = engine.trader.generate_positions_report()

    log.info(
        "backtest finished",
        ending_balance=(
            float(account_report["total"].iloc[-1]) if not account_report.empty else None
        ),
        positions=len(positions_report),
    )


if __name__ == "__main__":
    app()
