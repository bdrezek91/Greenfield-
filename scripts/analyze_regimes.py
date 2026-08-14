"""CLI to backtest a strategy and break its performance down by market
regime at trade entry, per docs/PHASE_0_ARCHITECTURE_RESEARCH.md section 13
("every strategy is analyzed separately across regimes").

Usage:
    python scripts/analyze_regimes.py --symbol BTCUSD --timeframe 1h \
        --strategy trend_following --start 2024-01-01 --end 2024-06-01
"""

from __future__ import annotations

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
from src.backtesting.runner import run_backtest_window
from src.data.config import load_symbol_universe
from src.data.storage import read_klines
from src.regimes.analysis import label_trades_with_regime, metrics_by_regime
from src.regimes.classifier import classify_regimes
from src.strategies.registry import ALL_STRATEGIES

log = structlog.get_logger()
app = typer.Typer(add_completion=False)


@app.command()
def analyze(
    symbol: str = typer.Option(..., help="Single symbol, e.g. BTCUSD."),
    timeframe: str = typer.Option("1h", help="Timeframe, e.g. 1h."),
    strategy: str = typer.Option(..., help=f"One of {list(ALL_STRATEGIES)}."),
    start: str = typer.Option(..., help="Start date, e.g. 2024-01-01"),
    end: str = typer.Option(..., help="End date, e.g. 2024-06-01"),
    data_dir: str | None = typer.Option(None, help="Defaults to $DATA_DIR or ./data"),
    starting_balance: float = typer.Option(100_000.0, help="Starting USD balance."),
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
    if strategy not in ALL_STRATEGIES:
        raise typer.BadParameter(
            f"unknown strategy {strategy!r}, expected one of {list(ALL_STRATEGIES)}",
            param_hint="--strategy",
        )

    resolved_data_dir = Path(data_dir or os.environ.get("DATA_DIR", "./data"))
    start_ts = pd.Timestamp(start, tz="UTC")
    end_ts = pd.Timestamp(end, tz="UTC")
    strategy_cls, config_cls = ALL_STRATEGIES[strategy]

    window = run_backtest_window(
        strategy_cls=strategy_cls,
        config_cls=config_cls,
        symbol=symbol,
        timeframe=timeframe,
        start=start_ts,
        end=end_ts,
        data_dir=resolved_data_dir,
        starting_balance=Decimal(str(starting_balance)),
        periods_per_year=periods_per_year,
    )
    if window.trades.empty:
        log.warning("no closed trades - nothing to break down by regime", strategy=strategy)
        return

    klines = read_klines(resolved_data_dir, symbol, timeframe, start=start_ts, end=end_ts)
    regimes = classify_regimes(klines)
    labeled_trades = label_trades_with_regime(window.trades, regimes)

    trend_breakdown = metrics_by_regime(labeled_trades, "trend_regime")
    vol_breakdown = metrics_by_regime(labeled_trades, "vol_regime")

    for regime, metrics in trend_breakdown.items():
        log.info(
            "trend regime breakdown",
            strategy=strategy,
            regime=regime,
            trades=metrics.trades,
            net_return=round(metrics.net_return, 2),
            win_rate=metrics.win_rate,
            profit_factor=metrics.profit_factor,
        )
    for regime, metrics in vol_breakdown.items():
        log.info(
            "vol regime breakdown",
            strategy=strategy,
            regime=regime,
            trades=metrics.trades,
            net_return=round(metrics.net_return, 2),
            win_rate=metrics.win_rate,
            profit_factor=metrics.profit_factor,
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
        strategy_version=f"{strategy}_by_regime",
        parameters={},
        fees={"model": "maker_taker_from_instrument"},
        slippage={"prob_slippage": 0.2},
        funding_assumptions={"note": "not applied in this run"},
        metrics={
            "overall": window.metrics.as_dict(),
            "by_trend_regime": {k: vars(v) for k, v in trend_breakdown.items()},
            "by_vol_regime": {k: vars(v) for k, v in vol_breakdown.items()},
        },
    )
    store.save(record)
    save_report(record)
    log.info("regime analysis finished", experiment_id=record.experiment_id)


if __name__ == "__main__":
    app()
