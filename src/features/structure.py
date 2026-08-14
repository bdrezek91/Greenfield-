"""Price structure features: higher-high/lower-low, breakout/breakdown flags.

Swing structure (HH/HL/LH/LL) is normally defined by comparing a
confirmed local extreme to a PRIOR local extreme - naive fractal detection
(comparing a bar's high to bars both before AND after it) is a lookahead
trap. This module avoids that entirely: instead of detecting individual
swing points, it compares two adjacent, non-overlapping trailing windows
ending at the current row (never using any bar after the current one) -
a coarser but strictly causal proxy for "is structure making higher highs
or lower lows."
"""

from __future__ import annotations

import pandas as pd


def higher_high(df: pd.DataFrame, lookback: int) -> pd.Series:
    """1.0 if the most recent `lookback`-bar high exceeds the `lookback`-bar
    high immediately before it (comparing two adjacent, non-overlapping,
    entirely-past-or-present windows), else 0.0.
    """
    recent_high = df["high"].rolling(window=lookback, min_periods=lookback).max()
    prior_high = recent_high.shift(lookback)
    return (recent_high > prior_high).astype(float).where(prior_high.notna())


def lower_low(df: pd.DataFrame, lookback: int) -> pd.Series:
    """Mirror of higher_high() for lows."""
    recent_low = df["low"].rolling(window=lookback, min_periods=lookback).min()
    prior_low = recent_low.shift(lookback)
    return (recent_low < prior_low).astype(float).where(prior_low.notna())


def breakout_flag(df: pd.DataFrame, lookback: int) -> pd.Series:
    """1.0 if the current close exceeds the PRIOR `lookback`-bar high
    (excluding the current bar itself), else 0.0."""
    prior_high = df["high"].shift(1).rolling(window=lookback, min_periods=lookback).max()
    return (df["close"] > prior_high).astype(float).where(prior_high.notna())


def breakdown_flag(df: pd.DataFrame, lookback: int) -> pd.Series:
    """Mirror of breakout_flag() for the downside."""
    prior_low = df["low"].shift(1).rolling(window=lookback, min_periods=lookback).min()
    return (df["close"] < prior_low).astype(float).where(prior_low.notna())
