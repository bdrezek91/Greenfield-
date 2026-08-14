"""Assemble the individual feature modules into one feature matrix.

The single entry point ML code (Phase 12) and research notebooks are meant
to use - keeps feature-set changes to one place rather than scattered
across callers, and gives every feature a stable, documented column name.
"""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from src.features import price, structure, volatility, volume


@dataclass(frozen=True)
class FeatureConfig:
    momentum_lookback: int = 10
    high_low_lookback: int = 20
    trend_slope_lookback: int = 20
    atr_period: int = 14
    realized_vol_period: int = 20
    range_percentile_lookback: int = 100
    relative_volume_lookback: int = 20
    volume_trend_lookback: int = 10
    structure_lookback: int = 10


def build_feature_matrix(df: pd.DataFrame, config: FeatureConfig | None = None) -> pd.DataFrame:
    """Return a new DataFrame of point-in-time features indexed the same as
    `df` (expects columns: timestamp, open, high, low, close, volume).
    Rows without enough trailing history are NaN, never a guessed value -
    callers (e.g. a training pipeline) are responsible for dropping or
    otherwise handling NaN rows explicitly.
    """
    config = config or FeatureConfig()
    out = pd.DataFrame(index=df.index)
    if "timestamp" in df.columns:
        out["timestamp"] = df["timestamp"]

    out["return_1"] = price.returns(df, periods=1)
    out["momentum"] = price.momentum(df, config.momentum_lookback)
    out["distance_from_high"] = price.distance_from_high(df, config.high_low_lookback)
    out["distance_from_low"] = price.distance_from_low(df, config.high_low_lookback)
    out["trend_slope"] = price.trend_slope(df, config.trend_slope_lookback)

    out["atr"] = volatility.atr(df, config.atr_period)
    out["realized_vol"] = volatility.realized_volatility(df, config.realized_vol_period)
    out["range_percentile"] = volatility.range_percentile(
        df, config.atr_period, config.range_percentile_lookback
    )

    out["relative_volume"] = volume.relative_volume(df, config.relative_volume_lookback)
    out["volume_trend"] = volume.volume_trend(df, config.volume_trend_lookback)

    out["higher_high"] = structure.higher_high(df, config.structure_lookback)
    out["lower_low"] = structure.lower_low(df, config.structure_lookback)
    out["breakout"] = structure.breakout_flag(df, config.structure_lookback)
    out["breakdown"] = structure.breakdown_flag(df, config.structure_lookback)

    return out


FEATURE_COLUMNS: tuple[str, ...] = (
    "return_1",
    "momentum",
    "distance_from_high",
    "distance_from_low",
    "trend_slope",
    "atr",
    "realized_vol",
    "range_percentile",
    "relative_volume",
    "volume_trend",
    "higher_high",
    "lower_low",
    "breakout",
    "breakdown",
)
