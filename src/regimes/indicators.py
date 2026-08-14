"""Technical indicators for regime classification.

Deliberately simple, non-ML indicators (ATR, ADX, moving-average structure,
realized volatility) per docs/PHASE_0_ARCHITECTURE_RESEARCH.md section 13:
market regime description starts with these, not AI.

Every function is a rolling/exponential calculation using only data up to
and including each row - no centering, no future lookahead. See
tests/lookahead/test_regime_no_lookahead.py for the protection test.
"""

from __future__ import annotations

import numpy as np
import pandas as pd


def true_range(df: pd.DataFrame) -> pd.Series:
    prev_close = df["close"].shift(1)
    ranges = pd.concat(
        [
            df["high"] - df["low"],
            (df["high"] - prev_close).abs(),
            (df["low"] - prev_close).abs(),
        ],
        axis=1,
    )
    return ranges.max(axis=1)


def atr(df: pd.DataFrame, period: int = 14) -> pd.Series:
    """Simple (SMA-based) Average True Range."""
    return true_range(df).rolling(window=period, min_periods=period).mean()


def directional_movement(df: pd.DataFrame) -> tuple[pd.Series, pd.Series]:
    up_move = df["high"].diff()
    down_move = -df["low"].diff()
    plus_dm = up_move.where((up_move > down_move) & (up_move > 0), 0.0)
    minus_dm = down_move.where((down_move > up_move) & (down_move > 0), 0.0)
    return plus_dm, minus_dm


def _wilder_smooth(series: pd.Series, period: int) -> pd.Series:
    """Wilder's smoothing, expressed as an EWM with alpha = 1/period."""
    return series.ewm(alpha=1 / period, adjust=False, min_periods=period).mean()


def adx(df: pd.DataFrame, period: int = 14) -> pd.Series:
    """Average Directional Index (Wilder). Measures trend STRENGTH, not
    direction - pair with moving_average_structure() for direction.
    """
    plus_dm, minus_dm = directional_movement(df)
    tr = true_range(df)

    smoothed_tr = _wilder_smooth(tr, period)
    smoothed_plus_dm = _wilder_smooth(plus_dm, period)
    smoothed_minus_dm = _wilder_smooth(minus_dm, period)

    plus_di = 100 * smoothed_plus_dm / smoothed_tr
    minus_di = 100 * smoothed_minus_dm / smoothed_tr
    dx = 100 * (plus_di - minus_di).abs() / (plus_di + minus_di)
    return _wilder_smooth(dx, period)


def realized_volatility(df: pd.DataFrame, period: int = 20) -> pd.Series:
    """Rolling standard deviation of log returns (not annualized - annualize
    in the caller if needed, since that depends on the timeframe).
    """
    log_returns = np.log(df["close"] / df["close"].shift(1))
    return log_returns.rolling(window=period, min_periods=period).std(ddof=1)


def moving_average_structure(
    df: pd.DataFrame, short_period: int = 20, long_period: int = 50
) -> pd.DataFrame:
    short_ma = df["close"].rolling(window=short_period, min_periods=short_period).mean()
    long_ma = df["close"].rolling(window=long_period, min_periods=long_period).mean()
    return pd.DataFrame({"short_ma": short_ma, "long_ma": long_ma})
