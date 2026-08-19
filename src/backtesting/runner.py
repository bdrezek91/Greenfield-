"""Shared orchestration: run one strategy through the backtest engine, and
optionally record the result as a reproducible experiment.

`run_backtest_window` is the low-level primitive (engine run -> trades/
equity/metrics, no recording) reused by both `run_and_record` (a single
recorded run, used by scripts/run_backtest.py and
scripts/compare_strategies.py) and src/backtesting/walk_forward.py (many
window runs, only the final TEST-period-only result gets recorded).
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path

import pandas as pd

from src.analytics.experiment import ExperimentRecord, ExperimentStore
from src.analytics.metrics import MetricsReport, compute_metrics
from src.analytics.report import save_report
from src.backtesting.costs import ExecutionAssumptions
from src.backtesting.data_adapter import bar_type_for
from src.backtesting.engine import BacktestRunSpec, build_engine
from src.backtesting.funding import FundingAssumptions
from src.backtesting.reports import account_report_to_equity, positions_report_to_trades


def serializable_params(config: object) -> dict:
    """Strategy-specific numeric/string parameters only - `config.dict()` also
    contains Nautilus objects (instrument_id, bar_type) that aren't JSON
    serializable and aren't parameters in the tuning sense anyway.
    """
    raw = config.dict()  # type: ignore[attr-defined]
    return {k: v for k, v in raw.items() if isinstance(v, int | float | str | bool)}


@dataclass
class BacktestWindowResult:
    trades: pd.DataFrame
    equity: pd.Series
    metrics: MetricsReport
    config: object
    funding_applied: bool
    mark_to_market_applied: bool


def run_backtest_window(
    *,
    strategy_cls: type,
    config_cls: type,
    symbol: str,
    timeframe: str,
    start: pd.Timestamp,
    end: pd.Timestamp,
    data_dir: Path,
    starting_balance: Decimal,
    periods_per_year: float,
    config_kwargs: dict | None = None,
    funding_assumptions: FundingAssumptions | None = None,
    execution: ExecutionAssumptions | None = None,
    mark_to_market: bool = True,
    reference_symbol: str | None = None,
) -> BacktestWindowResult:
    """Run one strategy over [start, end] and adapt the result into the
    generic trades/equity/metrics shape. No experiment is recorded.

    `funding_assumptions`: if given, perpetual funding is charged against
    every trade (including a still-open position, through `end`) via
    `src.backtesting.funding.estimate_funding_cost`. Omitting it means the
    run has no funding modeled at all - a real gap, not a silent zero, and
    it's recorded as `funding_applied=False` on the result so a caller (or
    the promotion gate) can refuse to call the run realistic.

    `execution`: fee/slippage/entry-delay assumptions actually wired into
    the engine (`src.backtesting.costs.ExecutionAssumptions`) - defaults to
    `ExecutionAssumptions()` (fee_multiplier=slippage_multiplier=1.0,
    entry_delay_bars=0) if omitted, i.e. `costs.base` from
    research_protocol.yaml. `entry_delay_bars` is injected into the
    strategy config (every `BenchmarkStrategyConfig` subclass has the
    field) so the SAME value drives both the venue's fee/fill model and
    the strategy's own delayed-entry behavior.

    `mark_to_market`: if True (the default) and a position is still open
    at `end`, it is marked to the last processed bar's close price and
    included in `trades` (see `positions_report_to_trades`) instead of
    being silently dropped.

    `reference_symbol`: if given, that symbol's instrument and bars are
    also loaded into the SAME engine run, and `reference_instrument_id`/
    `reference_bar_type` are added to `config_kwargs` before constructing
    the strategy config - for a cross-asset strategy
    (src.strategies.cross_asset_momentum) that needs a second instrument's
    data as a regime filter, not just the one it trades.
    """
    resolved_execution = execution or ExecutionAssumptions()
    spec = BacktestRunSpec(
        symbols=[symbol, *([reference_symbol] if reference_symbol else [])],
        timeframe=timeframe,
        start=start,
        end=end,
        data_dir=data_dir,
        starting_balance=starting_balance,
        execution=resolved_execution,
    )
    engine, instruments = build_engine(spec)
    instrument = instruments[symbol]
    bar_type = bar_type_for(instrument, timeframe)
    merged_kwargs = dict(config_kwargs or {})
    if reference_symbol is not None:
        reference_instrument = instruments[reference_symbol]
        merged_kwargs["reference_instrument_id"] = reference_instrument.id
        merged_kwargs["reference_bar_type"] = bar_type_for(reference_instrument, timeframe)
    # Strategies that read an auxiliary data source directly from disk
    # (e.g. src.strategies.funding_contrarian.FundingContrarian's funding/OI
    # series) declare a `data_dir` config field with no safe default - fill
    # it in here rather than asking every caller to know which strategies
    # need it.
    if "data_dir" in getattr(config_cls, "__struct_fields__", ()):
        merged_kwargs.setdefault("data_dir", str(data_dir))
    if "entry_delay_bars" in getattr(config_cls, "__struct_fields__", ()):
        merged_kwargs.setdefault("entry_delay_bars", resolved_execution.entry_delay_bars)
    config = config_cls(instrument_id=instrument.id, bar_type=bar_type, **merged_kwargs)
    engine.add_strategy(strategy_cls(config))
    engine.run()

    positions = engine.trader.generate_positions_report()
    account = engine.trader.generate_account_report(next(iter(engine.list_venues())))
    last_bar = engine.cache.bar(bar_type) if mark_to_market else None
    mark_price = float(last_bar.close) if last_bar is not None else None
    engine.dispose()

    trades = positions_report_to_trades(
        positions,
        period_end=end if mark_price is not None else None,
        mark_price=mark_price,
        funding_assumptions=funding_assumptions,
    )
    equity = account_report_to_equity(account)
    metrics = compute_metrics(
        trades, equity, period_start=start, period_end=end, periods_per_year=periods_per_year
    )
    return BacktestWindowResult(
        trades=trades,
        equity=equity,
        metrics=metrics,
        config=config,
        funding_applied=funding_assumptions is not None,
        mark_to_market_applied=mark_price is not None,
    )


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
    funding_assumptions: FundingAssumptions | None = None,
    execution: ExecutionAssumptions | None = None,
    extra_parameters: dict | None = None,
    reference_symbol: str | None = None,
) -> StrategyRunResult:
    window = run_backtest_window(
        strategy_cls=strategy_cls,
        config_cls=config_cls,
        symbol=symbol,
        timeframe=timeframe,
        start=start,
        end=end,
        data_dir=data_dir,
        starting_balance=starting_balance,
        periods_per_year=periods_per_year,
        config_kwargs=config_kwargs,
        funding_assumptions=funding_assumptions,
        execution=execution,
        reference_symbol=reference_symbol,
    )

    funding_meta = (
        {
            "applied": True,
            "rate_per_interval": str(funding_assumptions.rate_per_interval),
            "funding_hours_utc": list(funding_assumptions.funding_hours_utc),
            "total_funding_cost": window.metrics.trade_metrics.funding_costs,
        }
        if window.funding_applied and funding_assumptions is not None
        else {"applied": False, "note": "no funding_assumptions supplied for this run"}
    )

    record = ExperimentRecord(
        experiment_id=store.next_id(),
        git_commit=git_commit,
        dataset_version=dataset_version,
        date_range=(str(start.date()), str(end.date())),
        symbols=(symbol, reference_symbol) if reference_symbol else (symbol,),
        timeframes=(timeframe,),
        strategy_version=name,
        parameters={**serializable_params(window.config), **(extra_parameters or {})},
        fees={"model": "maker_taker_from_instrument"},
        slippage={"prob_slippage": 0.2},
        funding_assumptions=funding_meta,
        metrics={
            **window.metrics.as_dict(),
            "mark_to_market_applied": window.mark_to_market_applied,
        },
    )
    store.save(record)
    save_report(record)

    return StrategyRunResult(
        name=name,
        experiment_id=record.experiment_id,
        metrics=window.metrics,
        trades=window.trades,
        equity=window.equity,
    )
