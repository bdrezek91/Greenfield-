"""Portfolio-level aggregation across instruments.

Per docs/PHASE_0_ARCHITECTURE_RESEARCH.md section 30: don't judge only
individual pairs - portfolio-level equity, correlation, concentration,
drawdown, and exposure matter too.

Scope note: this module aggregates independently-run, single-symbol
backtest results post-hoc. It does not run one simultaneous multi-
instrument strategy sharing a single live risk budget - that's a larger
engineering lift, the same scope boundary src/risk/engine.py's docstring
flags for cross-instrument risk. `combine_equity_curves` assumes each
symbol was backtested with the same `starting_balance` (equal notional
capital allocated per symbol) - a simplification, not a claim that capital
was actually split and jointly compounded across symbols in one account.
"""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from src.analytics.metrics import exposure_fraction


@dataclass
class SymbolResult:
    symbol: str
    trades: pd.DataFrame
    equity: pd.Series


def combine_equity_curves(results: list[SymbolResult], starting_balance: float) -> pd.Series:
    """Sum each symbol's own PnL (equity minus its own first value) onto a
    shared timeline (forward-filled between each symbol's own observation
    points), then add back a single shared starting balance.

    Each symbol's raw equity series may have duplicate timestamps (multiple
    account events - e.g. order submission and fill - at the same instant,
    as NautilusTrader's account report records them); duplicates are
    collapsed to the last value at that timestamp before reindexing, since
    `Series.reindex` requires a unique index.
    """
    pnl_series = [
        (r.equity - r.equity.iloc[0]).groupby(level=0).last()
        for r in results
        if not r.equity.empty
    ]
    if not pnl_series:
        return pd.Series(dtype=float)

    combined_index = sorted(set().union(*(s.index for s in pnl_series)))
    aligned = [s.reindex(combined_index).ffill().fillna(0.0) for s in pnl_series]
    total_pnl = aligned[0]
    for series in aligned[1:]:
        total_pnl = total_pnl.add(series, fill_value=0.0)
    return starting_balance + total_pnl


def correlation_matrix(results: list[SymbolResult]) -> pd.DataFrame:
    """Pairwise correlation of each symbol's own period returns. Empty
    DataFrame if fewer than two symbols have enough equity history.
    """
    returns = {
        r.symbol: r.equity.pct_change().dropna() for r in results if len(r.equity) > 1
    }
    returns = {symbol: series for symbol, series in returns.items() if not series.empty}
    if len(returns) < 2:
        return pd.DataFrame()
    return pd.DataFrame(returns).corr()


def concentration_hhi(results: list[SymbolResult]) -> float:
    """Herfindahl-Hirschman Index of exposure concentration by symbol, based
    on each symbol's total absolute trade notional (sum of |quantity| *
    entry_price across its closed trades). 1/n_symbols (evenly split) is
    minimal concentration; 1.0 means all activity was in one symbol. NaN if
    no symbol has any trade notional at all.
    """
    notionals: dict[str, float] = {}
    for r in results:
        if r.trades.empty:
            notionals[r.symbol] = 0.0
        else:
            notionals[r.symbol] = float(
                (r.trades["quantity"].abs() * r.trades["entry_price"]).sum()
            )

    total = sum(notionals.values())
    if total <= 0:
        return float("nan")
    return sum((n / total) ** 2 for n in notionals.values())


def portfolio_drawdown(equity: pd.Series) -> float:
    """Max drawdown of a combined equity curve (see compute_equity_metrics
    in src.analytics.metrics for the single-symbol equivalent)."""
    if equity.empty:
        return 0.0
    running_max = equity.cummax()
    drawdown = equity / running_max - 1
    return float(drawdown.min())


def portfolio_exposure(
    results: list[SymbolResult], period_start: pd.Timestamp, period_end: pd.Timestamp
) -> float:
    """Fraction of [period_start, period_end] during which at least one
    symbol had an open position (union of intervals across symbols).
    """
    non_empty = [r.trades for r in results if not r.trades.empty]
    if not non_empty:
        return 0.0
    all_trades = pd.concat(non_empty, ignore_index=True)
    return exposure_fraction(all_trades, period_start, period_end)
