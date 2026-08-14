"""Price features: returns, momentum, distance from highs/lows, trend.

Per docs/PHASE_0_ARCHITECTURE_RESEARCH.md section 23. Every function is a
rolling calculation using only data up to and including each row - see
tests/lookahead/test_feature_no_lookahead.py.
"""

from __future__ import annotations

import numpy as np
import pandas as pd


def returns(df: pd.DataFrame, periods: int = 1, log: bool = False) -> pd.Series:
    if log:
        return np.log(df["close"] / df["close"].shift(periods))
    return df["close"].pct_change(periods)


def momentum(df: pd.DataFrame, lookback: int) -> pd.Series:
    """Fractional price change over `lookback` bars."""
    return df["close"] / df["close"].shift(lookback) - 1


def distance_from_high(df: pd.DataFrame, lookback: int) -> pd.Series:
    """(close - trailing N-bar high) / trailing N-bar high. <= 0; 0 means
    the current close IS the trailing high."""
    rolling_high = df["high"].rolling(window=lookback, min_periods=lookback).max()
    return df["close"] / rolling_high - 1


def distance_from_low(df: pd.DataFrame, lookback: int) -> pd.Series:
    """(close - trailing N-bar low) / trailing N-bar low. >= 0; 0 means the
    current close IS the trailing low."""
    rolling_low = df["low"].rolling(window=lookback, min_periods=lookback).min()
    return df["close"] / rolling_low - 1


def trend_slope(df: pd.DataFrame, lookback: int) -> pd.Series:
    """Least-squares slope of close over the trailing `lookback` bars,
    normalized by the window's mean price (so it's comparable across price
    levels/instruments). Positive = uptrend, negative = downtrend.
    """
    close = df["close"]
    x = np.arange(lookback, dtype=float)
    x_mean = x.mean()
    x_demeaned = x - x_mean
    denom = (x_demeaned**2).sum()

    def _slope(window: np.ndarray) -> float:
        y_mean = window.mean()
        if y_mean == 0:
            return np.nan
        cov = (x_demeaned * (window - y_mean)).sum()
        return (cov / denom) / y_mean

    return close.rolling(window=lookback, min_periods=lookback).apply(_slope, raw=True)
