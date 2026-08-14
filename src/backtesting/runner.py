"""Shared orchestration: run one strategy through the backtest engine and
record the result as a reproducible experiment.

Used by scripts/run_backtest.py (single ad-hoc run) and
scripts/compare_strategies.py (many strategies on the same data/costs) so
the two don't duplicate the engine-wiring-to-experiment-record pipeline.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path

import pandas as pd

from src.analytics.experiment import ExperimentRecord, ExperimentStore
from src.analytics.metrics import MetricsReport, compute_metrics
from src.analytics.report import save_report
from src.backtesting.data_adapter import bar_type_for
from src.backtesting.engine import BacktestRunSpec, build_engine
from src.backtesting.reports import account_report_to_equity, positions_report_to_trades


def _serializable_params(config: object) -> dict:
    """Strategy-specific numeric/string parameters only - `config.dict()` also
    contains Nautilus objects (instrument_id, bar_type) that aren't JSON
    serializable and aren't parameters in the tuning sense anyway.
    """
    raw = config.dict()  # type: ignore[attr-defined]
    return {k: v for k, v in raw.items() if isinstance(v, int | float | str | bool)}


@dataclass
class StrategyRunResult:
    name: str
    experiment_id: str
    metrics: MetricsReport
    trades: pd.DataFrame
    equity: pd.Series


def run_and_record(
    *,
    name: str,
    strategy_cls: type,
    config_cls: type,
    symbol: str,
    timeframe: str,
    start: pd.Timestamp,
    end: pd.Timestamp,
    data_dir: Path,
    starting_balance: Decimal,
    periods_per_year: float,
    store: ExperimentStore,
    git_commit: str,
    dataset_version: str,
    config_kwargs: dict | None = None,
) -> StrategyRunResult:
    spec = BacktestRunSpec(
        symbols=[symbol],
        timeframe=timeframe,
        start=start,
        end=end,
        data_dir=data_dir,
        starting_balance=starting_balance,
    )
    engine, instruments = build_engine(spec)
    instrument = instruments[symbol]
    bar_type = bar_type_for(instrument, timeframe)
    config = config_cls(instrument_id=instrument.id, bar_type=bar_type, **(config_kwargs or {}))
    engine.add_strategy(strategy_cls(config))
    engine.run()

    positions = engine.trader.generate_positions_report()
    account = engine.trader.generate_account_report(next(iter(engine.list_venues())))
    engine.dispose()

    trades = positions_report_to_trades(positions)
    equity = account_report_to_equity(account)
    metrics = compute_metrics(
        trades, equity, period_start=start, period_end=end, periods_per_year=periods_per_year
    )

    record = ExperimentRecord(
        experiment_id=store.next_id(),
        git_commit=git_commit,
        dataset_version=dataset_version,
        date_range=(str(start.date()), str(end.date())),
        symbols=(symbol,),
        timeframes=(timeframe,),
        strategy_version=name,
        parameters=_serializable_params(config),
        fees={"model": "maker_taker_from_instrument"},
        slippage={"prob_slippage": 0.2},
        funding_assumptions={"note": "not applied in this run"},
        metrics=metrics.as_dict(),
    )
    store.save(record)
    save_report(record)

    return StrategyRunResult(
        name=name,
        experiment_id=record.experiment_id,
        metrics=metrics,
        trades=trades,
        equity=equity,
    )
