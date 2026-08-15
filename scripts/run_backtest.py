"""CLI to run a NautilusTrader backtest against locally stored Parquet klines.

With no --strategy, no strategy is attached (Phase 3 behavior - proves the
data/instrument/venue/cost plumbing end to end, no experiment is recorded).
Pass --strategy to run one of the registered strategies (benchmarks or
families - see src/strategies/registry.py) against a single instrument; the
run is recorded as a reproducible experiment (src/analytics/experiment.py).

Usage:
    python scripts/run_backtest.py --start 2024-01-01 --end 2024-02-01
    python scripts/run_backtest.py --symbol BTCUSDT --timeframe 1h \
        --strategy trend_following --start 2024-01-01 --end 2024-02-01
"""

from __future__ import annotations

import os
from decimal import Decimal
from pathlib import Path

import pandas as pd
import structlog
import typer

from src.analytics.experiment import ExperimentStore, capture_git_commit, fingerprint_dataset
from src.backtesting.engine import BacktestRunSpec
from src.backtesting.engine import run_backtest as run_zero_strategy_backtest
from src.backtesting.runner import run_and_record
from src.data.config import load_symbol_universe
from src.strategies.registry import ALL_STRATEGIES

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
    strategy: str | None = typer.Option(
        None,
        help=f"One of {list(ALL_STRATEGIES)}. Requires --symbol. Default: no strategy.",
    ),
    periods_per_year: float = typer.Option(
        365.25 * 24, help="For annualizing Sharpe/Sortino; defaults to hourly bars."
    ),
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
    if strategy is not None:
        if symbol is None:
            raise typer.BadParameter(
                "--strategy requires --symbol (a strategy binds to one instrument)",
                param_hint="--strategy",
            )
        if strategy not in ALL_STRATEGIES:
            raise typer.BadParameter(
                f"unknown strategy {strategy!r}, expected one of {list(ALL_STRATEGIES)}",
                param_hint="--strategy",
            )

    symbols = [symbol] if symbol else list(universe.symbols)
    resolved_data_dir = Path(data_dir or os.environ.get("DATA_DIR", "./data"))
    start_ts = pd.Timestamp(start, tz="UTC")
    end_ts = pd.Timestamp(end, tz="UTC")

    log.info(
        "running backtest",
        symbols=symbols,
        timeframe=timeframe,
        start=start,
        end=end,
        strategy=strategy,
    )

    if strategy is None:
        spec = BacktestRunSpec(
            symbols=symbols,
            timeframe=timeframe,
            start=start_ts,
            end=end_ts,
            data_dir=resolved_data_dir,
            starting_balance=Decimal(str(starting_balance)),
        )
        engine = run_zero_strategy_backtest(spec)
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
        return

    strategy_cls, config_cls = ALL_STRATEGIES[strategy]
    repo_root = Path(__file__).resolve().parents[1]
    result = run_and_record(
        name=strategy,
        strategy_cls=strategy_cls,
        config_cls=config_cls,
        symbol=symbol,  # type: ignore[arg-type]
        timeframe=timeframe,
        start=start_ts,
        end=end_ts,
        data_dir=resolved_data_dir,
        starting_balance=Decimal(str(starting_balance)),
        periods_per_year=periods_per_year,
        store=ExperimentStore(),
        git_commit=capture_git_commit(repo_root),
        dataset_version=fingerprint_dataset(resolved_data_dir, symbol, timeframe),  # type: ignore[arg-type]
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
