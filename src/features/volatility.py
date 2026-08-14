"""Volatility features: ATR, realized volatility, range volatility percentile.

ATR and realized volatility are computed by src.regimes.indicators (Phase 8)
- reused here rather than duplicated, per the project's DRY convention.
"""

from __future__ import annotations

import pandas as pd

from src.regimes.indicators import atr, realized_volatility

__all__ = ["atr", "realized_volatility", "range_percentile"]


def range_percentile(df: pd.DataFrame, atr_period: int = 14, lookback: int = 100) -> pd.Series:
    """Percentile rank (0-1) of the current ATR within its own trailing
    `lookback` window - "is the current range wide or narrow relative to
    its own recent history," computed causally (the window ends at the
    current row, never looks ahead - same trailing-window convention as
    src.regimes.classifier's vol_regime).
    """
    atr_series = atr(df, atr_period)

    def _pct_rank(window: pd.Series) -> float:
        return float((window <= window.iloc[-1]).mean())

    return atr_series.rolling(window=lookback, min_periods=lookback).apply(_pct_rank, raw=False)
