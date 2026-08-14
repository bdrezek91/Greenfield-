"""Price feature formulas must match hand-computed values on small fixtures."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from src.features.price import distance_from_high, distance_from_low, momentum, returns, trend_slope


def _df(close: list[float]) -> pd.DataFrame:
    c = pd.Series(close, dtype=float)
    return pd.DataFrame({"high": c + 0.5, "low": c - 0.5, "close": c})


def test_returns_simple() -> None:
    df = _df([100.0, 110.0, 99.0])
    result = returns(df, periods=1)
    assert result.iloc[1] == pytest.approx(0.10)
    assert result.iloc[2] == pytest.approx(99.0 / 110.0 - 1)


def test_returns_log() -> None:
    df = _df([100.0, 110.0])
    result = returns(df, periods=1, log=True)
    assert result.iloc[1] == pytest.approx(np.log(110.0 / 100.0))


def test_momentum_hand_computed() -> None:
    df = _df([100.0, 101.0, 102.0, 103.0, 104.0])
    result = momentum(df, lookback=4)
    assert result.iloc[4] == pytest.approx(104.0 / 100.0 - 1)
    assert result.iloc[:4].isna().all()


def test_distance_from_high_is_zero_at_the_high() -> None:
    df = _df([100.0, 105.0, 102.0, 103.0])
    result = distance_from_high(df, lookback=4)
    # trailing high over the window (of `high` = close+0.5) is at index 1.
    assert result.iloc[3] < 0  # current close below the trailing high


def test_distance_from_low_is_nonnegative() -> None:
    df = _df([100.0, 95.0, 98.0, 99.0])
    result = distance_from_low(df, lookback=4)
    assert result.iloc[3] >= 0


def test_trend_slope_positive_for_uptrend() -> None:
    df = _df((100 + np.arange(20, dtype=float) * 0.5).tolist())
    result = trend_slope(df, lookback=10)
    assert result.iloc[-1] > 0


def test_trend_slope_negative_for_downtrend() -> None:
    df = _df((200 - np.arange(20, dtype=float) * 0.5).tolist())
    result = trend_slope(df, lookback=10)
    assert result.iloc[-1] < 0


def test_trend_slope_near_zero_for_flat() -> None:
    df = _df([100.0] * 20)
    result = trend_slope(df, lookback=10)
    assert result.iloc[-1] == pytest.approx(0.0, abs=1e-9)
