"""Volatility/volume/structure feature formulas."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from src.features.structure import breakdown_flag, breakout_flag, higher_high, lower_low
from src.features.volatility import range_percentile
from src.features.volume import relative_volume, volume_trend


def _trending_df(n: int = 60, step: float = 0.5, start: float = 100.0) -> pd.DataFrame:
    close = start + np.arange(n, dtype=float) * step
    return pd.DataFrame(
        {"high": close + 0.3, "low": close - 0.3, "close": close, "volume": 100.0 + np.arange(n)}
    )


def test_relative_volume_hand_computed() -> None:
    df = pd.DataFrame({"volume": [10.0, 10.0, 10.0, 10.0, 20.0]})
    result = relative_volume(df, lookback=4)
    assert result.iloc[4] == pytest.approx(20.0 / 10.0)


def test_volume_trend_hand_computed() -> None:
    df = pd.DataFrame({"volume": [10.0, 12.0, 14.0, 16.0, 20.0]})
    result = volume_trend(df, lookback=4)
    assert result.iloc[4] == pytest.approx(20.0 / 10.0 - 1)


def test_higher_high_true_on_uptrend() -> None:
    df = _trending_df()
    result = higher_high(df, lookback=10)
    assert result.iloc[-1] == 1.0


def test_lower_low_true_on_downtrend() -> None:
    df = _trending_df(step=-0.5, start=200.0)
    result = lower_low(df, lookback=10)
    assert result.iloc[-1] == 1.0


def test_higher_high_false_on_flat() -> None:
    df = _trending_df(step=0.0)
    result = higher_high(df, lookback=10)
    assert result.iloc[-1] == 0.0


def test_breakout_flag_fires_on_new_high() -> None:
    flat = pd.DataFrame({"high": [100.0] * 20, "low": [99.0] * 20, "close": [99.5] * 20})
    spike = pd.DataFrame({"high": [110.0], "low": [109.0], "close": [110.0]})
    df = pd.concat([flat, spike], ignore_index=True)
    result = breakout_flag(df, lookback=15)
    assert result.iloc[-1] == 1.0


def test_breakdown_flag_fires_on_new_low() -> None:
    flat = pd.DataFrame({"high": [100.0] * 20, "low": [99.0] * 20, "close": [99.5] * 20})
    drop = pd.DataFrame({"high": [90.0], "low": [89.0], "close": [89.0]})
    df = pd.concat([flat, drop], ignore_index=True)
    result = breakdown_flag(df, lookback=15)
    assert result.iloc[-1] == 1.0


def test_range_percentile_bounds() -> None:
    df = _trending_df(n=150)
    result = range_percentile(df, atr_period=14, lookback=100)
    valid = result.dropna()
    assert not valid.empty
    assert (valid >= 0).all() and (valid <= 1).all()


def test_warmup_rows_are_nan() -> None:
    df = _trending_df(n=10)
    assert higher_high(df, lookback=20).isna().all()
    assert breakout_flag(df, lookback=20).isna().all()
