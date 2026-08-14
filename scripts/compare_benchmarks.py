"""Run all four Phase 5 benchmarks on the same data/costs and compare them fairly.

This is the "framework for fair comparison" required by
docs/RESEARCH_METHODOLOGY.md and docs/PHASE_0_ARCHITECTURE_RESEARCH.md
section 11: every strategy runs through the same engine, the same cost
model, and the same fixed-fraction sizing/holding-period rule
(src/strategies/base.py) - only the entry signal differs. Each run is
recorded as an experiment (src/analytics/experiment.py).

Usage:
    python scripts/compare_benchmarks.py --symbol BTCUSDT --timeframe 1h \
        --start 2024-01-01 --end 2024-03-01
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
from src.analytics.metrics import compute_metrics
from src.analytics.report import save_report
from src.backtesting.data_adapter import bar_type_for
from src.backtesting.engine import BacktestRunSpec, build_engine
from src.backtesting.reports import account_report_to_equity, positions_report_to_trades
from src.data.config import load_symbol_universe
from src.strategies.registry import BENCHMARK_STRATEGIES

log = structlog.get_logger()
app = typer.Typer(add_completion=False)


def _serializable_params(config: object) -> dict:
    """Strategy-specific numeric/string parameters only - `config.dict()` also
    contains Nautilus objects (instrument_id, bar_type) that aren't JSON
    serializable and aren't parameters in the tuning sense anyway.
    """
    raw = config.dict()  # type: ignore[attr-defined]
    return {k: v for k, v in raw.items() if isinstance(v, int | float | str | bool)}


@app.command()
def compare(
    symbol: str = typer.Option(..., help="Single symbol, e.g. BTCUSDT."),
    timeframe: str = typer.Option("1h", help="Timeframe, e.g. 1h."),
    start: str = typer.Option(..., help="Start date, e.g. 2024-01-01"),
    end: str = typer.Option(..., help="End date, e.g. 2024-02-01"),
    data_dir: str | None = typer.Option(None, help="Defaults to $DATA_DIR or ./data"),
    starting_balance: float = typer.Option(100_000.0, help="Starting USDT balance."),
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
    store = ExperimentStore()
    repo_root = Path(__file__).resolve().parents[1]
    git_commit = capture_git_commit(repo_root)
    dataset_version = fingerprint_dataset(resolved_data_dir, symbol, timeframe)

    results = []
    for name, (strategy_cls, config_cls) in BENCHMARK_STRATEGIES.items():
        spec = BacktestRunSpec(
            symbols=[symbol],
            timeframe=timeframe,
            start=start_ts,
            end=end_ts,
            data_dir=resolved_data_dir,
            starting_balance=Decimal(str(starting_balance)),
        )
        engine, instruments = build_engine(spec)
        instrument = instruments[symbol]
        bar_type = bar_type_for(instrument, timeframe)
        config = config_cls(instrument_id=instrument.id, bar_type=bar_type)
        engine.add_strategy(strategy_cls(config))
        engine.run()

        positions = engine.trader.generate_positions_report()
        account = engine.trader.generate_account_report(next(iter(engine.list_venues())))
        engine.dispose()

        trades = positions_report_to_trades(positions)
        equity = account_report_to_equity(account)
        report = compute_metrics(
            trades, equity, period_start=start_ts, period_end=end_ts,
            periods_per_year=periods_per_year,
        )

        record = ExperimentRecord(
            experiment_id=store.next_id(),
            git_commit=git_commit,
            dataset_version=dataset_version,
            date_range=(start, end),
            symbols=(symbol,),
            timeframes=(timeframe,),
            strategy_version=name,
            parameters=_serializable_params(config),
            fees={"model": "maker_taker_from_instrument"},
            slippage={"prob_slippage": 0.2},
            funding_assumptions={"note": "not applied in this comparison"},
            metrics=report.as_dict(),
        )
        store.save(record)
        save_report(record)
        results.append((name, record.experiment_id, report))

        log.info(
            "strategy finished",
            strategy=name,
            experiment_id=record.experiment_id,
            trades=report.trade_metrics.trades,
            net_return=round(report.trade_metrics.net_return, 2),
            sharpe=report.equity_metrics.sharpe,
            max_drawdown=report.equity_metrics.max_drawdown,
        )

    log.info("comparison finished", strategies=[r[0] for r in results])


if __name__ == "__main__":
    app()
