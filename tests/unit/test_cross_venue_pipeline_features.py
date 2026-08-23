"""build_feature_matrix's optional cross-venue context feature family
(Cycle 35 - closes the last easily-wireable gap from the Cycle 26-31
survey: src.features.cross_venue's cross_venue_snapshot is a POINT-in-time,
one-row-per-venue function, incompatible with a direct as-of join -
Cycle 35 first built cross_venue_series_frame (a new walk-forward wrapper,
same pattern as Cycle 27's rolling_volume_profile_frame) before wiring
was possible.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from src.features.cross_venue import cross_venue_series_frame
from src.features.pipeline import (
    CROSS_VENUE_CONTEXT_FEATURE_COLUMNS,
    FEATURE_COLUMNS,
    build_feature_matrix,
)


def _ohlcv(n: int, seed: int = 0) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    close = 100 + np.cumsum(rng.normal(0.02, 0.6, size=n))
    ts = pd.date_range("2024-01-01", periods=n, freq="1h", tz="UTC")
    return pd.DataFrame(
        {
            "timestamp": ts,
            "high": close + 0.5,
            "low": close - 0.5,
            "close": close,
            "volume": 100.0 + rng.normal(0, 10, size=n).cumsum().clip(min=0),
        }
    )


def _quotes(ts: pd.Series) -> pd.DataFrame:
    """Three venues per bar, okx a consistent price outlier."""
    rows = []
    for t in ts:
        rows.append(
            {"timestamp": t, "max_source_timestamp": t, "exchange": "bybit",
             "canonical_instrument_id": "BTC-USDT:PERP:USDT", "mid_price": 100.0}
        )
        rows.append(
            {"timestamp": t, "max_source_timestamp": t, "exchange": "binance",
             "canonical_instrument_id": "BTC-USDT:PERP:USDT", "mid_price": 100.1}
        )
        rows.append(
            {"timestamp": t, "max_source_timestamp": t, "exchange": "okx",
             "canonical_instrument_id": "BTC-USDT:PERP:USDT", "mid_price": 102.0}
        )
    return pd.DataFrame(rows)


def test_omitting_cross_venue_context_leaves_output_unchanged() -> None:
    df = _ohlcv(20)
    out = build_feature_matrix(df)

    assert "cross_venue_count" not in out.columns
    assert set(FEATURE_COLUMNS).issubset(out.columns)


def test_cross_venue_context_columns_present_and_reflect_a_real_outlier() -> None:
    df = _ohlcv(5)
    quotes = _quotes(df["timestamp"])
    context = cross_venue_series_frame(
        quotes,
        canonical_instrument_id="BTC-USDT:PERP:USDT",
        as_of_timestamps=df["timestamp"],
        max_deviation_bps=50,
    )

    out = build_feature_matrix(df, cross_venue_context=context)

    assert set(CROSS_VENUE_CONTEXT_FEATURE_COLUMNS).issubset(out.columns)
    assert (out["cross_venue_count"] == 3).all()
    assert (out["cross_venue_outlier_count"] == 1).all()
    # cross_venue_median_price (raw) must not leak through unconverted -
    # only the close-relative distance is exposed.
    assert "cross_venue_median_price" not in out.columns


def test_cross_venue_context_is_as_of_joined_never_a_future_reading() -> None:
    df = _ohlcv(10)
    quotes = _quotes(df["timestamp"])
    full_context = cross_venue_series_frame(
        quotes,
        canonical_instrument_id="BTC-USDT:PERP:USDT",
        as_of_timestamps=df["timestamp"],
    )
    # Only give the pipeline context up through bar 5 - later bars must
    # not see values that "arrived" after their own timestamp.
    partial_context = full_context.iloc[:6].copy()

    out = build_feature_matrix(df, cross_venue_context=partial_context)

    assert (
        out["cross_venue_count"].iloc[6:] == out["cross_venue_count"].iloc[5]
    ).all()
