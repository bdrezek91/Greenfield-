"""Adapt NautilusTrader's report DataFrames into the generic contracts
src.analytics.metrics expects (see that module's docstring). This is the
only place besides engine.py/data_adapter.py that touches NautilusTrader's
report shapes - the analytics layer stays engine-independent.
"""

from __future__ import annotations

import pandas as pd

TRADE_COLUMNS = ("entry_time", "exit_time", "quantity", "entry_price", "exit_price", "fees")


def _parse_money(value: str) -> float:
    """NautilusTrader renders Money as e.g. '12.09949327 USDT' - take the numeric part."""
    return float(value.split(" ")[0])


def positions_report_to_trades(positions: pd.DataFrame) -> pd.DataFrame:
    """Only closed positions become trades - one still open at the end of a
    backtest isn't a completed round trip yet.
    """
    if positions.empty:
        return pd.DataFrame(columns=TRADE_COLUMNS)

    ts_closed = pd.to_datetime(positions["ts_closed"], utc=True, errors="coerce")
    closed = positions[ts_closed.notna()].copy()
    if closed.empty:
        return pd.DataFrame(columns=TRADE_COLUMNS)

    closed["ts_closed"] = pd.to_datetime(closed["ts_closed"], utc=True)
    direction = closed["entry"].map({"BUY": 1.0, "SELL": -1.0})
    fees = closed["commissions"].apply(
        lambda entries: sum(_parse_money(entry) for entry in entries) if entries else 0.0
    )

    return pd.DataFrame(
        {
            "entry_time": closed["ts_opened"],
            "exit_time": closed["ts_closed"],
            "quantity": closed["peak_qty"].astype(float) * direction,
            "entry_price": closed["avg_px_open"].astype(float),
            "exit_price": closed["avg_px_close"].astype(float),
            "fees": fees,
            "funding_cost": 0.0,
        }
    ).reset_index(drop=True)


def account_report_to_equity(account: pd.DataFrame) -> pd.Series:
    """The account report's `total` balance over time, indexed by timestamp -
    an event-driven (irregularly sampled) equity curve, not fixed-interval
    bars. Fine for cumulative metrics (net return, CAGR, drawdown); Sharpe/
    Sortino's annualization is an approximation under irregular sampling.
    """
    if account.empty:
        return pd.Series(dtype=float)
    return account["total"].astype(float)
