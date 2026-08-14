"""Indicator formulas must match hand-computed values on small fixtures, and
respond correctly to trending vs. flat/noisy synthetic data.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from src.regimes.indicators import (
    adx,
    atr,
    directional_movement,
    moving_average_structure,
    realized_volatility,
    true_range,
)


def _ohlc(high: list[float], low: list[float], close: list[float]) -> pd.DataFrame:
    return pd.DataFrame({"high": high, "low": low, "close": close})


def test_true_range_hand_computed() -> None:
    df = _ohlc(high=[10, 12, 11], low=[8, 9, 9], close=[9, 11, 10])
    tr = true_range(df)
    # Row 0: no prev close -> just high-low = 2.
    # Row 1: high-low=3, |high-prevclose|=|12-9|=3, |low-prevclose|=|9-9|=0 -> 3.
    # Row 2: high-low=2, |high-prevclose|=|11-11|=0, |low-prevclose|=|9-11|=2 -> 2.
    assert tr.tolist() == pytest.approx([2.0, 3.0, 2.0])


def test_directional_movement_up_move() -> None:
    df = _ohlc(high=[10, 13, 13], low=[8, 9, 7], close=[9, 12, 10])
    plus_dm, minus_dm = directional_movement(df)
    # Row 1: up_move=3, down_move=-1 (low rose) -> plus_dm=3, minus_dm=0.
    assert plus_dm.iloc[1] == pytest.approx(3.0)
    assert minus_dm.iloc[1] == pytest.approx(0.0)


def test_directional_movement_down_move() -> None:
    df = _ohlc(high=[10, 10, 10], low=[8, 4, 4], close=[9, 6, 6])
    plus_dm, minus_dm = directional_movement(df)
    # Row 1: up_move=0, down_move=4 -> plus_dm=0, minus_dm=4.
    assert plus_dm.iloc[1] == pytest.approx(0.0)
    assert minus_dm.iloc[1] == pytest.approx(4.0)


def test_atr_is_rolling_mean_of_true_range() -> None:
    close = [100.0, 101.0, 102.0, 101.0, 103.0]
    df = _ohlc(high=[c + 1 for c in close], low=[c - 1 for c in close], close=close)
    result = atr(df, period=3)
    assert result.iloc[:2].isna().all()
    expected_third = true_range(df).iloc[0:3].mean()
    assert result.iloc[2] == pytest.approx(expected_third)


def test_atr_warmup_is_nan() -> None:
    df = _ohlc(high=[11, 12], low=[9, 10], close=[10, 11])
    result = atr(df, period=14)
    assert result.isna().all()


def test_adx_high_for_pure_uptrend() -> None:
    close = 100 + np.arange(100, dtype=float) * 0.5
    df = _ohlc(high=close + 0.3, low=close - 0.3, close=close)
    result = adx(df, period=14)
    assert result.iloc[-1] > 80  # near-maximal trend strength


def test_adx_low_for_flat_noise() -> None:
    close = 100 + np.random.default_rng(0).normal(0, 0.05, size=100)
    df = _ohlc(high=close + 0.3, low=close - 0.3, close=close)
    result = adx(df, period=14)
    assert result.iloc[-1] < 20  # weak/no trend


def test_realized_volatility_zero_for_constant_returns() -> None:
    close = 100 * (1.001 ** np.arange(50))  # constant per-period return
    df = _ohlc(high=close, low=close, close=close)
    result = realized_volatility(df, period=20)
    assert result.iloc[-1] == pytest.approx(0.0, abs=1e-10)


def test_realized_volatility_higher_for_noisier_series() -> None:
    low_noise = 100 + np.cumsum(np.random.default_rng(1).normal(0, 0.05, size=200))
    high_noise = 100 + np.cumsum(np.random.default_rng(1).normal(0, 2.0, size=200))
    df_low = _ohlc(high=low_noise, low=low_noise, close=low_noise)
    df_high = _ohlc(high=high_noise, low=high_noise, close=high_noise)
    vol_low = realized_volatility(df_low, period=20).iloc[-1]
    vol_high = realized_volatility(df_high, period=20).iloc[-1]
    assert vol_high > vol_low


def test_moving_average_structure_hand_computed() -> None:
    close = [1.0, 2.0, 3.0, 4.0, 5.0]
    df = _ohlc(high=close, low=close, close=close)
    result = moving_average_structure(df, short_period=2, long_period=4)
    assert result["short_ma"].iloc[1] == pytest.approx(1.5)
    assert result["short_ma"].iloc[4] == pytest.approx(4.5)
    assert result["long_ma"].iloc[3] == pytest.approx(2.5)
    assert result["long_ma"].iloc[:3].isna().all()
