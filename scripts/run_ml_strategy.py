"""CLI to run the Phase 13 AI-enhanced strategy (src/strategies/ml_filtered.py)
against locally stored Parquet klines and record it as a reproducible
experiment - the ml_filtered counterpart to scripts/run_backtest.py, kept
separate because MLFilteredConfig.model_path has no default (see
src/strategies/registry.py's AI_ENHANCED_STRATEGIES docstring).

Usage:
    python scripts/run_ml_strategy.py --symbol BTCUSD --timeframe 1h \
        --start 2024-04-01 --end 2024-06-01 \
        --model-path reports/models/btc_1h_logreg.joblib \
        --probability-threshold 0.55
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
from src.strategies.registry import AI_ENHANCED_STRATEGIES

log = structlog.get_logger()
app = typer.Typer(add_completion=False)


@app.command()
def run(
    symbol: str = typer.Option(..., help="Single symbol, e.g. BTCUSD."),
    timeframe: str = typer.Option("1h", help="Timeframe, e.g. 1h."),
    start: str = typer.Option(..., help="Start date, e.g. 2024-04-01"),
    end: str = typer.Option(..., help="End date, e.g. 2024-06-01"),
    data_dir: str | None = typer.Option(None, help="Defaults to $DATA_DIR or ./data"),
    starting_balance: float = typer.Option(100_000.0, help="Starting USD balance."),
    model_path: str = typer.Option(..., help="Path to a model exported by export_ml_model.py."),
    probability_threshold: float = typer.Option(0.55, help="Minimum P(win) to take a trade."),
    periods_per_year: float = typer.Option(
        365.25 * 24, help="For annualizing Sharpe/Sortino; defaults to hourly bars."
    ),
) -> None:
    universe = load_symbol_universe()
    try:
        universe.validate_symbol(symbol)
        universe.validate_timeframe(timeframe)
    except ValueError as exc:
        raise typer.BadParameter(str(exc)) from exc

    resolved_data_dir = Path(data_dir or os.environ.get("DATA_DIR", "./data"))
    start_ts = pd.Timestamp(start, tz="UTC")
    end_ts = pd.Timestamp(end, tz="UTC")

    log.info(
        "running ml_filtered backtest",
        symbol=symbol,
        timeframe=timeframe,
        start=start,
        end=end,
        model_path=model_path,
    )

    strategy_cls, config_cls = AI_ENHANCED_STRATEGIES["ml_filtered"]
    repo_root = Path(__file__).resolve().parents[1]
    result = run_and_record(
        name="ml_filtered",
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
        config_kwargs={
            "model_path": model_path,
            "probability_threshold": probability_threshold,
        },
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
