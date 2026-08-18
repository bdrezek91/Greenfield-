"""Walk-forward framework: sliding TRAIN/VALIDATION/TEST windows.

Per docs/RESEARCH_METHODOLOGY.md: never evaluate a strategy on the data it
was optimized on. The final reported equity curve and trade set are
assembled from consecutive TEST periods only.

If `param_grid` is given, each candidate config is backtested on the
VALIDATION window and the one with the best `selection_metric` is chosen
for that window's TEST run - selection happens on VALIDATION, never on
TEST. If no grid is given, the single provided config runs on TEST directly
(no optimization is claimed - this is the honest behavior when a strategy
has no tunable parameter grid defined yet).

Known limitation: each window's TEST run starts from a fresh
`starting_balance` (a new BacktestEngine/venue per window), not a
continuously compounding account carried across windows. `_stitch_equity_
curves` reconstructs one continuous curve by compounding each window's own
period returns rather than concatenating raw balances (which would show a
spurious reset at every window boundary) - but position sizing itself
(fixed-fraction-of-equity, src/strategies/sizing.py) is still computed
relative to each window's own fresh balance, not the stitched one. This is
a reasonable approximation for research purposes, not a claim that this
matches how a continuously-deployed account would behave.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path

import pandas as pd

from src.analytics.metrics import MetricsReport, compute_metrics
from src.backtesting.costs import ExecutionAssumptions
from src.backtesting.data_adapter import timeframe_delta
from src.backtesting.funding import FundingAssumptions
from src.backtesting.runner import run_backtest_window


@dataclass(frozen=True)
class WalkForwardWindow:
    train_start: pd.Timestamp
    train_end: pd.Timestamp
    validation_start: pd.Timestamp
    validation_end: pd.Timestamp
    test_start: pd.Timestamp
    test_end: pd.Timestamp


def generate_windows(
    start: pd.Timestamp,
    end: pd.Timestamp,
    train_period: pd.Timedelta,
    validation_period: pd.Timedelta,
    test_period: pd.Timedelta,
    *,
    purge_bars: int = 0,
    embargo_bars: int = 0,
    timeframe: str | None = None,
) -> list[WalkForwardWindow]:
    """Slide a TRAIN/VALIDATION/TEST window forward by `test_period` each
    step (the standard "anchored to TEST" walk-forward scheme) until the
    next TEST window would run past `end`.
    """
    zero = pd.Timedelta(0)
    if train_period <= zero or validation_period <= zero or test_period <= zero:
        raise ValueError("train/validation/test periods must all be positive")

    if purge_bars < 0 or embargo_bars < 0:
        raise ValueError("purge_bars and embargo_bars must be non-negative")
    if (purge_bars or embargo_bars) and timeframe is None:
        raise ValueError("timeframe is required when purge/embargo are enabled")
    gap = (
        timeframe_delta(timeframe) * (purge_bars + embargo_bars)
        if timeframe is not None
        else pd.Timedelta(0)
    )
    windows = []
    train_start = start
    while True:
        train_end = train_start + train_period
        validation_start = train_end + gap
        validation_end = validation_start + validation_period
        test_start = validation_end + gap
        test_end = test_start + test_period
        if test_end > end:
            break
        windows.append(
            WalkForwardWindow(
                train_start=train_start,
                train_end=train_end,
                validation_start=validation_start,
                validation_end=validation_end,
                test_start=test_start,
                test_end=test_end,
            )
        )
        train_start = train_start + test_period
    return windows


def _stitch_equity_curves(equity_segments: list[pd.Series], starting_balance: float) -> pd.Series:
    """Chain per-window TEST equity curves into one continuous curve by
    compounding each window's own period returns - see module docstring.
    """
    non_empty = [s for s in equity_segments if not s.empty]
    if not non_empty:
        return pd.Series(dtype=float)

    all_returns = [s.pct_change().dropna() for s in non_empty]
    all_returns = [r for r in all_returns if not r.empty]
    first_ts = non_empty[0].index[0]

    if not all_returns:
        return pd.Series([starting_balance], index=[first_ts])

    combined_returns = pd.concat(all_returns)
    equity_values = starting_balance * (1 + combined_returns).cumprod()

    index = pd.Index([first_ts]).append(combined_returns.index)
    values = [starting_balance, *equity_values.tolist()]
    return pd.Series(values, index=index)


@dataclass
class WalkForwardResult:
    windows: list[WalkForwardWindow]
    selected_params: list[dict]
    test_trades: pd.DataFrame
    test_equity: pd.Series
    metrics: MetricsReport
    funding_applied: bool
    mark_to_market_applied: bool
    fee_applied: bool
    slippage_applied: bool
    spread_applied: bool
    delay_applied: bool
    missed_trades_applied: bool


def run_walk_forward(
    *,
    strategy_cls: type,
    config_cls: type,
    symbol: str,
    timeframe: str,
    windows: list[WalkForwardWindow],
    data_dir: Path,
    starting_balance: Decimal,
    periods_per_year: float,
    param_grid: list[dict] | None = None,
    selection_metric: str = "sharpe",
    funding_assumptions: FundingAssumptions | None = None,
    reference_symbol: str | None = None,
    execution: ExecutionAssumptions | None = None,
) -> WalkForwardResult:
    if not windows:
        raise ValueError(
            "no walk-forward windows to run - the date range is too short for the "
            "given train/validation/test periods"
        )

    all_trades: list[pd.DataFrame] = []
    equity_segments: list[pd.Series] = []
    selected_params: list[dict] = []
    funding_applied_all = True
    mark_to_market_applied_all = True
    fee_applied_all = True
    slippage_applied_all = True
    spread_applied_all = True
    delay_applied_all = True
    missed_trades_applied_all = True

    for window in windows:
        chosen_kwargs = _select_params(
            strategy_cls=strategy_cls,
            config_cls=config_cls,
            symbol=symbol,
            timeframe=timeframe,
            window=window,
            data_dir=data_dir,
            starting_balance=starting_balance,
            periods_per_year=periods_per_year,
            param_grid=param_grid,
            selection_metric=selection_metric,
            funding_assumptions=funding_assumptions,
            reference_symbol=reference_symbol,
            execution=execution,
        )
        selected_params.append(chosen_kwargs)

        test_result = run_backtest_window(
            strategy_cls=strategy_cls,
            config_cls=config_cls,
            symbol=symbol,
            timeframe=timeframe,
            start=window.test_start,
            end=window.test_end,
            data_dir=data_dir,
            starting_balance=starting_balance,
            periods_per_year=periods_per_year,
            config_kwargs=chosen_kwargs,
            funding_assumptions=funding_assumptions,
            reference_symbol=reference_symbol,
            execution=execution,
        )
        all_trades.append(test_result.trades)
        equity_segments.append(test_result.equity)
        funding_applied_all = funding_applied_all and test_result.funding_applied
        mark_to_market_applied_all = (
            mark_to_market_applied_all and test_result.mark_to_market_applied
        )
        fee_applied_all = fee_applied_all and test_result.fee_applied
        slippage_applied_all = slippage_applied_all and test_result.slippage_applied
        spread_applied_all = spread_applied_all and test_result.spread_applied
        delay_applied_all = delay_applied_all and test_result.delay_applied
        missed_trades_applied_all = (
            missed_trades_applied_all and test_result.missed_trades_applied
        )

    combined_trades = pd.concat(all_trades, ignore_index=True)
    combined_equity = _stitch_equity_curves(equity_segments, float(starting_balance))

    metrics = compute_metrics(
        combined_trades,
        combined_equity,
        period_start=windows[0].test_start,
        period_end=windows[-1].test_end,
        periods_per_year=periods_per_year,
    )

    return WalkForwardResult(
        windows=windows,
        selected_params=selected_params,
        test_trades=combined_trades,
        test_equity=combined_equity,
        metrics=metrics,
        funding_applied=funding_applied_all,
        mark_to_market_applied=mark_to_market_applied_all,
        fee_applied=fee_applied_all,
        slippage_applied=slippage_applied_all,
        spread_applied=spread_applied_all,
        delay_applied=delay_applied_all,
        missed_trades_applied=missed_trades_applied_all,
    )


def _select_params(
    *,
    strategy_cls: type,
    config_cls: type,
    symbol: str,
    timeframe: str,
    window: WalkForwardWindow,
    data_dir: Path,
    starting_balance: Decimal,
    periods_per_year: float,
    param_grid: list[dict] | None,
    selection_metric: str,
    funding_assumptions: FundingAssumptions | None = None,
    reference_symbol: str | None = None,
    execution: ExecutionAssumptions | None = None,
) -> dict:
    if not param_grid:
        return {}

    best_kwargs: dict | None = None
    best_score = float("-inf")
    for kwargs in param_grid:
        result = run_backtest_window(
            strategy_cls=strategy_cls,
            config_cls=config_cls,
            symbol=symbol,
            timeframe=timeframe,
            start=window.validation_start,
            end=window.validation_end,
            data_dir=data_dir,
            starting_balance=starting_balance,
            periods_per_year=periods_per_year,
            config_kwargs=kwargs,
            funding_assumptions=funding_assumptions,
            reference_symbol=reference_symbol,
            execution=execution,
        )
        score = getattr(result.metrics.equity_metrics, selection_metric, None)
        if score is None:
            score = getattr(result.metrics.trade_metrics, selection_metric, None)
        if score is not None and not math.isnan(score) and score > best_score:
            best_score = score
            best_kwargs = kwargs

    return best_kwargs if best_kwargs is not None else param_grid[0]
