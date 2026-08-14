"""CLI to backtest a strategy and run a Monte Carlo simulation (min. 10,000
sims per docs/RESEARCH_METHODOLOGY.md section 19) over its trade sequence.

Usage:
    python scripts/monte_carlo.py --symbol BTCUSD --timeframe 1h \
        --strategy trend_following --start 2024-01-01 --end 2024-06-01
"""

from __future__ import annotations

import os
from decimal import Decimal
from pathlib import Path

import pandas as pd
import structlog
import typer

from src.analytics.metrics import trade_pnl
from src.analytics.monte_carlo import run_monte_carlo
from src.backtesting.runner import run_backtest_window
from src.data.config import load_symbol_universe
from src.strategies.registry import ALL_STRATEGIES

log = structlog.get_logger()
app = typer.Typer(add_completion=False)


@app.command()
def monte_carlo(
    symbol: str = typer.Option(..., help="Single symbol, e.g. BTCUSD."),
    timeframe: str = typer.Option("1h", help="Timeframe, e.g. 1h."),
    strategy: str = typer.Option(..., help=f"One of {list(ALL_STRATEGIES)}."),
    start: str = typer.Option(..., help="Start date, e.g. 2024-01-01"),
    end: str = typer.Option(..., help="End date, e.g. 2024-06-01"),
    data_dir: str | None = typer.Option(None, help="Defaults to $DATA_DIR or ./data"),
    starting_balance: float = typer.Option(100_000.0, help="Starting USD balance."),
    n_simulations: int = typer.Option(10_000, help="Minimum 10,000 per project methodology."),
    ruin_threshold: float = typer.Option(0.5, help="Drawdown fraction counted as ruin."),
    seed: int | None = typer.Option(None, help="Random seed for reproducibility."),
) -> None:
    universe = load_symbol_universe()
    try:
        universe.validate_symbol(symbol)
        universe.validate_timeframe(timeframe)
    except ValueError as exc:
        raise typer.BadParameter(str(exc)) from exc
    if strategy not in ALL_STRATEGIES:
        raise typer.BadParameter(
            f"unknown strategy {strategy!r}, expected one of {list(ALL_STRATEGIES)}",
            param_hint="--strategy",
        )
    if n_simulations < 10_000:
        log.warning(
            "n_simulations below the project's methodology minimum of 10,000",
            n_simulations=n_simulations,
        )

    resolved_data_dir = Path(data_dir or os.environ.get("DATA_DIR", "./data"))
    strategy_cls, config_cls = ALL_STRATEGIES[strategy]

    result = run_backtest_window(
        strategy_cls=strategy_cls,
        config_cls=config_cls,
        symbol=symbol,
        timeframe=timeframe,
        start=pd.Timestamp(start, tz="UTC"),
        end=pd.Timestamp(end, tz="UTC"),
        data_dir=resolved_data_dir,
        starting_balance=Decimal(str(starting_balance)),
        periods_per_year=365.25 * 24,
    )

    if result.trades.empty:
        log.warning("no closed trades - nothing to simulate", strategy=strategy)
        return

    net_pnl = trade_pnl(result.trades)["net_pnl"]
    mc = run_monte_carlo(
        net_pnl,
        n_simulations=n_simulations,
        starting_equity=starting_balance,
        ruin_threshold=ruin_threshold,
        seed=seed,
    )

    log.info("monte carlo finished", strategy=strategy, **mc.summary())


if __name__ == "__main__":
    app()
