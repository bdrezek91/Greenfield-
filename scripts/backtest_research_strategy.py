"""CLI to backtest a research-only strategy (funding_oi, price_action,
cross_asset, multi_horizon_trend families - see src/strategies/registry.py)
through the same recorded backtest path as scripts/run_backtest.py.

These strategies are deliberately excluded from ALL_STRATEGIES because their
config has a field with no safe default (data_dir, reference_symbol,
higher_timeframe) - src/backtesting/runner.py's run_backtest_window already
knows how to fill in data_dir automatically, so this script only needs to
expose that superset (RESEARCH_STRATEGIES) instead of ALL_STRATEGIES.

Usage:
    python scripts/backtest_research_strategy.py --symbol BTCUSDT \\
        --timeframe 1h --strategy funding_contrarian \\
        --start 2024-01-01 --end 2024-07-01
"""

from __future__ import annotations

import os
from decimal import Decimal
from pathlib import Path

import pandas as pd
import structlog
import typer

from src.analytics.experiment import ExperimentStore, capture_git_commit, fingerprint_dataset
from src.backtesting.runner import run_and_record
from src.data.config import load_symbol_universe
from src.strategies.registry import RESEARCH_STRATEGIES

log = structlog.get_logger()
app = typer.Typer(add_completion=False)


@app.command()
def backtest(
    symbol: str = typer.Option(..., help="Single symbol, e.g. BTCUSDT."),
    timeframe: str = typer.Option("1h", help="Timeframe, e.g. 1h."),
    strategy: str = typer.Option(..., help=f"One of {list(RESEARCH_STRATEGIES)}."),
    start: str = typer.Option(..., help="Start date, e.g. 2024-01-01"),
    end: str = typer.Option(..., help="End date, e.g. 2024-02-01"),
    data_dir: str | None = typer.Option(None, help="Defaults to $DATA_DIR or ./data"),
    starting_balance: float = typer.Option(10_000.0, help="Starting USDT balance."),
    periods_per_year: float = typer.Option(
        365.25 * 24, help="For annualizing Sharpe/Sortino; defaults to hourly bars."
    ),
) -> None:
    universe = load_symbol_universe()
    try:
        universe.validate_symbol(symbol)
    except ValueError as exc:
        raise typer.BadParameter(str(exc), param_hint="--symbol") from exc
    try:
        universe.validate_timeframe(timeframe)
    except ValueError as exc:
        raise typer.BadParameter(str(exc), param_hint="--timeframe") from exc
    if strategy not in RESEARCH_STRATEGIES:
        raise typer.BadParameter(
            f"unknown strategy {strategy!r}, expected one of {list(RESEARCH_STRATEGIES)}",
            param_hint="--strategy",
        )

    resolved_data_dir = Path(data_dir or os.environ.get("DATA_DIR", "./data"))
    start_ts = pd.Timestamp(start, tz="UTC")
    end_ts = pd.Timestamp(end, tz="UTC")

    log.info(
        "running research backtest",
        symbol=symbol,
        timeframe=timeframe,
        start=start,
        end=end,
        strategy=strategy,
    )

    strategy_cls, config_cls = RESEARCH_STRATEGIES[strategy]
    repo_root = Path(__file__).resolve().parents[1]
    result = run_and_record(
        name=strategy,
        strategy_cls=strategy_cls,
        config_cls=config_cls,
        symbol=symbol,
        timeframe=timeframe,
        start=start_ts,
        end=end_ts,
        data_dir=resolved_data_dir,
        starting_balance=Decimal(str(starting_balance)),
        periods_per_year=periods_per_year,
        store=ExperimentStore(),
        git_commit=capture_git_commit(repo_root),
        dataset_version=fingerprint_dataset(resolved_data_dir, symbol, timeframe),
    )
    log.info(
        "backtest finished",
        experiment_id=result.experiment_id,
        trades=result.metrics.trade_metrics.trades,
        net_return=round(result.metrics.trade_metrics.net_return, 2),
        sharpe=result.metrics.equity_metrics.sharpe,
    )


if __name__ == "__main__":
    app()
