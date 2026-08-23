"""build_feature_matrix's optional volume-profile/VWAP features (Cycle 27
- continues Cycle 26's wiring of orphaned src/features/ modules into
build_feature_matrix, this time src.features.auction's
rolling_volume_profile_frame/anchored_vwap_frame). Raw price levels
(poc/vah/val/vwap) are converted to close-relative, scale-invariant
features here rather than joined as-is - see
src.features.pipeline.build_feature_matrix's docstring.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from src.features.pipeline import (
    FEATURE_COLUMNS,
    VOLUME_PROFILE_FEATURE_COLUMNS,
    VWAP_FEATURE_COLUMNS,
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


def test_omitting_volume_profile_and_vwap_leaves_output_unchanged() -> None:
    df = _ohlcv(60)
    out = build_feature_matrix(df)

    assert "poc_distance" not in out.columns
    assert "vwap_distance" not in out.columns
    assert set(FEATURE_COLUMNS).issubset(out.columns)


def test_volume_profile_and_vwap_are_independent_extras() -> None:
    df = _ohlcv(10)
    profile = pd.DataFrame(
        {
            "timestamp": df["timestamp"],
            "poc": df["close"],
            "vah": df["close"] + 1.0,
            "val": df["close"] - 1.0,
        }
    )

    out_profile_only = build_feature_matrix(df, volume_profile=profile)
    assert set(VOLUME_PROFILE_FEATURE_COLUMNS).issubset(out_profile_only.columns)
    assert "vwap_distance" not in out_profile_only.columns

    vwap = pd.DataFrame({"timestamp": df["timestamp"], "vwap": df["close"]})
    out_vwap_only = build_feature_matrix(df, vwap=vwap)
    assert set(VWAP_FEATURE_COLUMNS).issubset(out_vwap_only.columns)
    assert "poc_distance" not in out_vwap_only.columns


def test_poc_distance_is_close_relative_not_a_raw_price() -> None:
    df = _ohlcv(5)
    profile = pd.DataFrame(
        {
            "timestamp": df["timestamp"],
            "poc": df["close"] * 0.99,  # 1% below close
            "vah": df["close"] * 1.02,
            "val": df["close"] * 0.98,
        }
    )

    out = build_feature_matrix(df, volume_profile=profile)

    np.testing.assert_allclose(out["poc_distance"].to_numpy(), 0.01, atol=1e-9)


def test_in_value_area_flags_close_inside_val_vah_range() -> None:
    df = _ohlcv(3)
    profile = pd.DataFrame(
        {
            "timestamp": df["timestamp"],
            "poc": df["close"],
            "val": [df["close"].iloc[0] - 1, df["close"].iloc[1] + 1, df["close"].iloc[2] - 1],
            "vah": [df["close"].iloc[0] + 1, df["close"].iloc[1] + 2, df["close"].iloc[2] + 1],
        }
    )

    out = build_feature_matrix(df, volume_profile=profile)

    assert out["in_value_area"].iloc[0] == 1.0  # close is inside [val, vah]
    assert out["in_value_area"].iloc[1] == 0.0  # close is below val
    assert out["in_value_area"].iloc[2] == 1.0


def test_volume_profile_features_are_nan_before_the_first_reading() -> None:
    df = _ohlcv(10)
    # Profile history only starts partway through the bar series - the
    # first several bars have no full trailing rolling-profile window.
    profile = pd.DataFrame(
        {
            "timestamp": [df["timestamp"].iloc[5]],
            "poc": [df["close"].iloc[5]],
            "vah": [df["close"].iloc[5] + 1],
            "val": [df["close"].iloc[5] - 1],
        }
    )

    out = build_feature_matrix(df, volume_profile=profile)

    assert out["poc_distance"].iloc[:5].isna().all()
    assert out["in_value_area"].iloc[:5].isna().all()
    assert out["poc_distance"].iloc[5:].notna().all()


def test_vwap_distance_is_close_relative() -> None:
    df = _ohlcv(3)
    vwap = pd.DataFrame({"timestamp": df["timestamp"], "vwap": df["close"] * 0.95})

    out = build_feature_matrix(df, vwap=vwap)

    np.testing.assert_allclose(out["vwap_distance"].to_numpy(), 0.05, atol=1e-9)
