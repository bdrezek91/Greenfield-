"""Volume features: relative volume, volume trend."""

from __future__ import annotations

import pandas as pd


def relative_volume(df: pd.DataFrame, lookback: int = 20) -> pd.Series:
    """Current volume / average volume over the PRIOR `lookback` bars
    (excluding the current bar, so a volume spike doesn't dilute its own
    baseline). 1.0 = typical, >1 = above-average activity.
    """
    avg_volume = df["volume"].shift(1).rolling(window=lookback, min_periods=lookback).mean()
    return df["volume"] / avg_volume


def volume_trend(df: pd.DataFrame, lookback: int) -> pd.Series:
    """Fractional change in volume over `lookback` bars (same shape as
    src.features.price.momentum, applied to volume instead of price)."""
    return df["volume"] / df["volume"].shift(lookback) - 1
