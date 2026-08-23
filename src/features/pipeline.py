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


def build_feature_matrix(
    df: pd.DataFrame,
    config: FeatureConfig | None = None,
    *,
    funding: pd.DataFrame | None = None,
    open_interest: pd.DataFrame | None = None,
    trade_flow: pd.DataFrame | None = None,
    l2_imbalance: pd.DataFrame | None = None,
) -> pd.DataFrame:
    """Return a new DataFrame of point-in-time features indexed the same as
    `df` (expects columns: timestamp, open, high, low, close, volume).
    Rows without enough trailing history are NaN, never a guessed value -
    callers (e.g. a training pipeline) are responsible for dropping or
    otherwise handling NaN rows explicitly.

    `funding`/`open_interest`/`trade_flow`/`l2_imbalance` are all optional
    and independent (default None -> output is exactly FEATURE_COLUMNS,
    unchanged from before any of them existed - existing callers/saved
    models are unaffected regardless of which extras a caller adds later).

    `funding`/`open_interest`: frames from src/data/storage.py's
    read_funding/read_open_interest (columns timestamp+funding_rate /
    timestamp+open_interest) - see EXTENDED_FEATURE_COLUMNS.

    `trade_flow`/`l2_imbalance`: frames from
    src.features.order_flow.trade_flow_frame/l2_imbalance_frame (built
    from normalized Silver trade/order-book rows, NOT computed here - this
    function only as-of joins pre-computed frames onto `df`'s bar
    timestamps, matching how funding/open_interest are handled) - see
    TRADE_FLOW_FEATURE_COLUMNS/L2_IMBALANCE_FEATURE_COLUMNS. Each is its
    own independent extra (a caller may have trade data without L2 data,
    or vice versa), unlike funding/open_interest, which this module has
    always treated as an all-or-nothing pair.

    Every extra is as-of joined to the most recent reading at or before
    each bar - never a future one.
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

    if funding is not None:
        out["funding_rate"] = _as_of_join(df["timestamp"], funding, "funding_rate")
    if open_interest is not None:
        oi = _as_of_join(df["timestamp"], open_interest, "open_interest")
        out["oi_change"] = oi.pct_change()
    if trade_flow is not None:
        out["cvd"] = _as_of_join(df["timestamp"], trade_flow, "cvd")
        out["trade_delta"] = _as_of_join(df["timestamp"], trade_flow, "trade_delta")
    if l2_imbalance is not None:
        out["book_imbalance"] = _as_of_join(df["timestamp"], l2_imbalance, "book_imbalance")
        out["spread"] = _as_of_join(df["timestamp"], l2_imbalance, "spread")

    return out


def _as_of_join(timestamps: pd.Series, source: pd.DataFrame, value_col: str) -> pd.Series:
    """Point-in-time as-of join: for each bar timestamp, the most recent
    `value_col` reading at or before it (never a future one).
    """
    left = pd.DataFrame({"timestamp": timestamps}).sort_values("timestamp")
    right = source[["timestamp", value_col]].sort_values("timestamp")
    merged = pd.merge_asof(left, right, on="timestamp", direction="backward")
    return merged.set_index(left.index)[value_col].reindex(timestamps.index)


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

# FEATURE_COLUMNS plus the optional funding/open-interest features - only
# present in build_feature_matrix()'s output when `funding`/`open_interest`
# are passed in. A caller opting into these must pass both `funding` and
# `open_interest` and use this tuple (not FEATURE_COLUMNS) as the model's
# feature schema.
EXTENDED_FEATURE_COLUMNS: tuple[str, ...] = FEATURE_COLUMNS + ("funding_rate", "oi_change")

# Present only when `trade_flow`/`l2_imbalance` (src.features.order_flow's
# trade_flow_frame/l2_imbalance_frame) are passed in - each independent of
# the other and of EXTENDED_FEATURE_COLUMNS's funding/OI pair. A caller
# combines whichever tuples match the extras it actually passed, e.g.
# `FEATURE_COLUMNS + TRADE_FLOW_FEATURE_COLUMNS` for trade flow alone.
TRADE_FLOW_FEATURE_COLUMNS: tuple[str, ...] = ("cvd", "trade_delta")
L2_IMBALANCE_FEATURE_COLUMNS: tuple[str, ...] = ("book_imbalance", "spread")
