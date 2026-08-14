"""Metrics required by docs/RESEARCH_METHODOLOGY.md, computed from two generic contracts:

- `trades`: one row per closed trade, columns:
    entry_time, exit_time (tz-aware UTC), quantity (signed: +long/-short),
    entry_price, exit_price, fees, funding_cost,
    and optionally mae, mfe (adverse/favorable excursion, in price units),
    r_multiple (pnl / initial risk, if the strategy defines a stop).
- `equity`: a `pd.Series` of account equity indexed by tz-aware UTC timestamp.

Both are deliberately decoupled from NautilusTrader's report shapes so this
module can be tested and used independently of the engine - the same
adapter pattern used in src/backtesting/funding.py.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np
import pandas as pd


def trade_pnl(trades: pd.DataFrame) -> pd.DataFrame:
    """Add `gross_pnl` and `net_pnl` columns (does not mutate the input)."""
    df = trades.copy()
    df["gross_pnl"] = df["quantity"] * (df["exit_price"] - df["entry_price"])
    df["net_pnl"] = df["gross_pnl"] - df.get("fees", 0.0) - df.get("funding_cost", 0.0)
    return df


def longest_losing_streak(net_pnl: pd.Series) -> int:
    longest = current = 0
    for pnl in net_pnl:
        if pnl < 0:
            current += 1
            longest = max(longest, current)
        else:
            current = 0
    return longest


def exposure_fraction(
    trades: pd.DataFrame, period_start: pd.Timestamp, period_end: pd.Timestamp
) -> float:
    """Fraction of [period_start, period_end] during which at least one trade was open."""
    if trades.empty or period_end <= period_start:
        return 0.0

    intervals = sorted(
        (max(row.entry_time, period_start), min(row.exit_time, period_end))
        for row in trades.itertuples()
        if row.exit_time > period_start and row.entry_time < period_end
    )
    if not intervals:
        return 0.0

    merged: list[list[pd.Timestamp]] = [list(intervals[0])]
    for start, end in intervals[1:]:
        if start <= merged[-1][1]:
            merged[-1][1] = max(merged[-1][1], end)
        else:
            merged.append([start, end])

    covered = sum((end - start).total_seconds() for start, end in merged)
    total = (period_end - period_start).total_seconds()
    return covered / total if total > 0 else 0.0


@dataclass
class TradeMetrics:
    trades: int
    net_return: float
    win_rate: float
    avg_win: float
    avg_loss: float
    expectancy: float
    profit_factor: float
    avg_r: float | None
    median_r: float | None
    longest_losing_streak: int
    turnover: float
    fees: float
    funding_costs: float
    avg_mae: float | None
    avg_mfe: float | None


def compute_trade_metrics(trades: pd.DataFrame) -> TradeMetrics:
    if trades.empty:
        return TradeMetrics(
            trades=0,
            net_return=0.0,
            win_rate=float("nan"),
            avg_win=float("nan"),
            avg_loss=float("nan"),
            expectancy=float("nan"),
            profit_factor=float("nan"),
            avg_r=None,
            median_r=None,
            longest_losing_streak=0,
            turnover=0.0,
            fees=0.0,
            funding_costs=0.0,
            avg_mae=None,
            avg_mfe=None,
        )

    df = trade_pnl(trades)
    wins = df.loc[df["net_pnl"] > 0, "net_pnl"]
    losses = df.loc[df["net_pnl"] < 0, "net_pnl"]
    gross_profit = wins.sum()
    gross_loss = losses.sum()

    return TradeMetrics(
        trades=len(df),
        net_return=float(df["net_pnl"].sum()),
        win_rate=float((df["net_pnl"] > 0).mean()),
        avg_win=float(wins.mean()) if not wins.empty else 0.0,
        avg_loss=float(losses.mean()) if not losses.empty else 0.0,
        expectancy=float(df["net_pnl"].mean()),
        profit_factor=float(gross_profit / abs(gross_loss)) if gross_loss != 0 else float("inf"),
        avg_r=float(df["r_multiple"].mean()) if "r_multiple" in df else None,
        median_r=float(df["r_multiple"].median()) if "r_multiple" in df else None,
        longest_losing_streak=longest_losing_streak(df.sort_values("exit_time")["net_pnl"]),
        turnover=float((df["quantity"].abs() * df["entry_price"]).sum()),
        fees=float(df.get("fees", pd.Series(dtype=float)).sum()),
        funding_costs=float(df.get("funding_cost", pd.Series(dtype=float)).sum()),
        avg_mae=float(df["mae"].mean()) if "mae" in df else None,
        avg_mfe=float(df["mfe"].mean()) if "mfe" in df else None,
    )


@dataclass
class EquityMetrics:
    cagr: float
    sharpe: float
    sortino: float
    calmar: float
    max_drawdown: float
    ulcer_index: float


def compute_equity_metrics(equity: pd.Series, periods_per_year: float) -> EquityMetrics:
    if len(equity) < 2:
        return EquityMetrics(
            cagr=float("nan"),
            sharpe=float("nan"),
            sortino=float("nan"),
            calmar=float("nan"),
            max_drawdown=0.0,
            ulcer_index=0.0,
        )

    equity = equity.sort_index()
    returns = equity.pct_change().dropna()

    years = (equity.index[-1] - equity.index[0]).total_seconds() / (365.25 * 86400)
    cagr = (
        (equity.iloc[-1] / equity.iloc[0]) ** (1 / years) - 1
        if years > 0 and equity.iloc[0] > 0
        else float("nan")
    )

    std = returns.std(ddof=1)
    annualization = math.sqrt(periods_per_year)
    sharpe = float(returns.mean() / std * annualization) if std > 0 else float("nan")

    downside = returns[returns < 0]
    downside_std = downside.std(ddof=1) if len(downside) > 1 else 0.0
    sortino = (
        float(returns.mean() / downside_std * annualization)
        if downside_std > 0
        else float("nan")
    )

    running_max = equity.cummax()
    drawdown = equity / running_max - 1
    max_drawdown = float(drawdown.min())
    calmar = (
        float(cagr / abs(max_drawdown))
        if max_drawdown < 0 and not math.isnan(cagr)
        else float("nan")
    )
    ulcer_index = float(np.sqrt((drawdown**2).mean()) * 100)

    return EquityMetrics(
        cagr=float(cagr),
        sharpe=sharpe,
        sortino=sortino,
        calmar=calmar,
        max_drawdown=max_drawdown,
        ulcer_index=ulcer_index,
    )


@dataclass
class MetricsReport:
    trade_metrics: TradeMetrics
    equity_metrics: EquityMetrics
    exposure: float

    def as_dict(self) -> dict:
        return {**vars(self.trade_metrics), **vars(self.equity_metrics), "exposure": self.exposure}


def compute_metrics(
    trades: pd.DataFrame,
    equity: pd.Series,
    period_start: pd.Timestamp,
    period_end: pd.Timestamp,
    periods_per_year: float,
) -> MetricsReport:
    return MetricsReport(
        trade_metrics=compute_trade_metrics(trades),
        equity_metrics=compute_equity_metrics(equity, periods_per_year),
        exposure=exposure_fraction(trades, period_start, period_end),
    )
