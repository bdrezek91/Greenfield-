"""CLI to run a strategy through the walk-forward framework and record the
result as one experiment (the concatenated TEST-only equity curve/trades).

Usage:
    python scripts/run_walk_forward.py --symbol BTCUSDT --timeframe 1h \
        --strategy trend_following --start 2024-01-01 --end 2024-06-01 \
        --train-days 60 --validation-days 15 --test-days 15

    # With a parameter grid (selected on VALIDATION per window):
    python scripts/run_walk_forward.py --symbol BTCUSDT --strategy momentum \
        --start 2024-01-01 --end 2024-06-01 \
        --param-grid '[{"threshold": 0.005}, {"threshold": 0.02}]'
"""

from __future__ import annotations

import json
import os
from decimal import Decimal
from pathlib import Path

import pandas as pd
import structlog
import typer

from src.analytics.experiment import (
    ExperimentRecord,
    ExperimentStore,
    capture_git_commit,
    fingerprint_dataset,
)
from src.analytics.report import save_report
from src.backtesting.annualization import resolve_periods_per_year
from src.backtesting.funding import FundingAssumptions
from src.backtesting.walk_forward import generate_windows, run_walk_forward
from src.data.config import load_symbol_universe
from src.strategies.registry import ALL_STRATEGIES

log = structlog.get_logger()
app = typer.Typer(add_completion=False)


@app.command()
def walk_forward(
    symbol: str = typer.Option(..., help="Single symbol, e.g. BTCUSDT."),
    timeframe: str = typer.Option("1h", help="Timeframe, e.g. 1h."),
    strategy: str = typer.Option(..., help=f"One of {list(ALL_STRATEGIES)}."),
    start: str = typer.Option(..., help="Start date, e.g. 2024-01-01"),
    end: str = typer.Option(..., help="End date, e.g. 2024-06-01"),
    train_days: int = typer.Option(60, help="TRAIN window length in days."),
    validation_days: int = typer.Option(15, help="VALIDATION window length in days."),
    test_days: int = typer.Option(15, help="TEST window length in days (also the slide step)."),
    data_dir: str | None = typer.Option(None, help="Defaults to $DATA_DIR or ./data"),
    starting_balance: float = typer.Option(100_000.0, help="Starting USDT balance."),
    periods_per_year: float | None = typer.Option(
        None,
        help=(
            "For annualizing Sharpe/Sortino/Calmar. Defaults to the value "
            "implied by --timeframe (e.g. 4h -> 365.25*6); pass this to "
            "override - the override is recorded explicitly in the "
            "experiment's parameters, never applied silently."
        ),
    ),
    param_grid: str | None = typer.Option(
        None, help='JSON list of parameter dicts, e.g. \'[{"threshold": 0.01}]\'.'
    ),
    selection_metric: str = typer.Option(
        "sharpe", help="Metric used to pick params on VALIDATION."
    ),
    apply_funding: bool = typer.Option(
        True,
        help=(
            "Charge perpetual funding against every trade (incl. a "
            "still-open position through the window end). Disabling this "
            "is recorded explicitly; docs/AUTONOMOUS_RESEARCH_AUDIT.md "
            "finding M2 - a run without funding is not a realistic backtest."
        ),
    ),
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

    resolved_data_dir = Path(data_dir or os.environ.get("DATA_DIR", "./data"))
    start_ts = pd.Timestamp(start, tz="UTC")
    end_ts = pd.Timestamp(end, tz="UTC")
    parsed_grid = json.loads(param_grid) if param_grid else None
    resolved_periods_per_year, periods_per_year_source = resolve_periods_per_year(
        timeframe, periods_per_year
    )
    funding_assumptions = FundingAssumptions() if apply_funding else None

    windows = generate_windows(
        start_ts,
        end_ts,
        train_period=pd.Timedelta(days=train_days),
        validation_period=pd.Timedelta(days=validation_days),
        test_period=pd.Timedelta(days=test_days),
    )
    if not windows:
        raise typer.BadParameter(
            "date range is too short for the given train/validation/test periods"
        )
    log.info("generated windows", n_windows=len(windows))

    strategy_cls, config_cls = ALL_STRATEGIES[strategy]
    result = run_walk_forward(
        strategy_cls=strategy_cls,
        config_cls=config_cls,
        symbol=symbol,
        timeframe=timeframe,
        windows=windows,
        data_dir=resolved_data_dir,
        starting_balance=Decimal(str(starting_balance)),
        periods_per_year=resolved_periods_per_year,
        param_grid=parsed_grid,
        selection_metric=selection_metric,
        funding_assumptions=funding_assumptions,
    )

    funding_meta = (
        {
            "applied": True,
            "rate_per_interval": str(funding_assumptions.rate_per_interval),
            "funding_hours_utc": list(funding_assumptions.funding_hours_utc),
            "total_funding_cost": result.metrics.trade_metrics.funding_costs,
        }
        if result.funding_applied and funding_assumptions is not None
        else {"applied": False, "note": "--no-apply-funding was passed for this run"}
    )

    repo_root = Path(__file__).resolve().parents[1]
    store = ExperimentStore()
    record = ExperimentRecord(
        experiment_id=store.next_id(),
        git_commit=capture_git_commit(repo_root),
        dataset_version=fingerprint_dataset(resolved_data_dir, symbol, timeframe),
        date_range=(start, end),
        symbols=(symbol,),
        timeframes=(timeframe,),
        strategy_version=f"{strategy}_walk_forward",
        parameters={
            "train_days": train_days,
            "validation_days": validation_days,
            "test_days": test_days,
            "param_grid": parsed_grid,
            "selected_params_per_window": result.selected_params,
            "periods_per_year": resolved_periods_per_year,
            "periods_per_year_source": periods_per_year_source,
        },
        fees={"model": "maker_taker_from_instrument"},
        slippage={"prob_slippage": 0.2},
        funding_assumptions=funding_meta,
        metrics={
            **result.metrics.as_dict(),
            "mark_to_market_applied": result.mark_to_market_applied,
        },
    )
    store.save(record)
    save_report(record)

    log.info(
        "walk-forward finished",
        experiment_id=record.experiment_id,
        periods_per_year=resolved_periods_per_year,
        periods_per_year_source=periods_per_year_source,
        funding_applied=result.funding_applied,
        mark_to_market_applied=result.mark_to_market_applied,
        n_windows=len(windows),
        trades=result.metrics.trade_metrics.trades,
        net_return=round(result.metrics.trade_metrics.net_return, 2),
        cagr=result.metrics.equity_metrics.cagr,
        sharpe=result.metrics.equity_metrics.sharpe,
        max_drawdown=result.metrics.equity_metrics.max_drawdown,
    )


if __name__ == "__main__":
    app()
