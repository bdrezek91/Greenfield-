"""Rule-based market regime classification.

Combines trend direction (moving-average structure) and strength (ADX) with
volatility level (realized volatility vs. its own trailing history) into
regime labels, per docs/PHASE_0_ARCHITECTURE_RESEARCH.md section 13:
UPTREND, DOWNTREND, RANGE, HIGH_VOL, LOW_VOL. No AI/ML - simple, auditable
rules, deliberately (section 13: "don't start with AI").
"""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from src.regimes.indicators import adx, atr, moving_average_structure, realized_volatility


@dataclass(frozen=True)
class RegimeConfig:
    short_ma_period: int = 20
    long_ma_period: int = 50
    adx_period: int = 14
    adx_trend_threshold: float = 25.0
    vol_period: int = 20
    vol_lookback: int = 100  # trailing window for the HIGH/LOW_VOL median threshold
    atr_period: int = 14


def classify_regimes(df: pd.DataFrame, config: RegimeConfig | None = None) -> pd.DataFrame:
    """Add `trend_regime`, `vol_regime`, and the underlying indicator columns
    to a copy of `df` (expects columns: timestamp, open, high, low, close).

    Rows before enough history has accumulated get a `pd.NA` label - never a
    guessed or defaulted regime, consistent with the project's "no silent
    assumptions" principle.
    """
    config = config or RegimeConfig()
    out = df.copy()

    ma = moving_average_structure(df, config.short_ma_period, config.long_ma_period)
    out["short_ma"] = ma["short_ma"]
    out["long_ma"] = ma["long_ma"]
    out["adx"] = adx(df, config.adx_period)
    out["atr"] = atr(df, config.atr_period)
    out["realized_vol"] = realized_volatility(df, config.vol_period)
    out["vol_median"] = out["realized_vol"].rolling(
        window=config.vol_lookback, min_periods=config.vol_lookback
    ).median()

    out["trend_regime"] = _trend_regime(out, config)
    out["vol_regime"] = _vol_regime(out)
    return out


def _trend_regime(df: pd.DataFrame, config: RegimeConfig) -> pd.Series:
    has_data = df["short_ma"].notna() & df["long_ma"].notna() & df["adx"].notna()
    is_trending = df["adx"] >= config.adx_trend_threshold
    is_up = df["short_ma"] > df["long_ma"]

    regime = pd.Series(pd.NA, index=df.index, dtype="object")
    regime[has_data & is_trending & is_up] = "UPTREND"
    regime[has_data & is_trending & ~is_up] = "DOWNTREND"
    regime[has_data & ~is_trending] = "RANGE"
    return regime


def _vol_regime(df: pd.DataFrame) -> pd.Series:
    """HIGH_VOL/LOW_VOL relative to the trailing `vol_lookback` window's own
    median. This makes it a volatility-SHIFT detector, not an absolute
    classifier: deep inside any single homogeneous-volatility stretch the
    split naturally hovers near 50/50 (a median split of same-distribution
    data does that by construction) - the reliable signal is right after a
    genuine volatility change, while the window still reflects the old
    level. See tests/unit/test_classifier.py for the behavior this implies.
    """
    has_data = df["realized_vol"].notna() & df["vol_median"].notna()
    is_high = df["realized_vol"] > df["vol_median"]

    regime = pd.Series(pd.NA, index=df.index, dtype="object")
    regime[has_data & is_high] = "HIGH_VOL"
    regime[has_data & ~is_high] = "LOW_VOL"
    return regime
