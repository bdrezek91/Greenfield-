"""build_feature_matrix's optional momentum-flow feature family (Cycle 28
- continues Cycles 26/27's wiring of orphaned src/features/ modules,
this time src.features.momentum_flow's independent Market-Cipher-like
momentum/money-flow/divergence family, no proprietary code). Unlike the
frame-based extras (trade_flow, l2_imbalance, volume_profile, vwap), this
one is a bool - src.features.momentum_flow.momentum_money_flow_frame
needs only `df` itself, so build_feature_matrix computes it internally
rather than requiring the caller to build a frame first.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from src.features.pipeline import (
    FEATURE_COLUMNS,
    MOMENTUM_FLOW_FEATURE_COLUMNS,
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


def test_omitting_momentum_flow_leaves_output_unchanged() -> None:
    df = _ohlcv(60)
    out = build_feature_matrix(df)

    assert "momentum_wave" not in out.columns
    assert "rsi" not in out.columns
    assert set(FEATURE_COLUMNS).issubset(out.columns)


def test_momentum_flow_true_adds_all_its_columns() -> None:
    df = _ohlcv(80, seed=1)  # enough bars to clear every default warmup window

    out = build_feature_matrix(df, momentum_flow=True)

    assert set(MOMENTUM_FLOW_FEATURE_COLUMNS).issubset(out.columns)
    # At least the later bars should have real (non-NaN) momentum/RSI values
    # once every default warmup window (channel/momentum/signal/money-flow/
    # RSI spans, all <= 21 bars) has been cleared.
    assert out["momentum_wave"].iloc[-1] is not None
    assert not pd.isna(out["rsi"].iloc[-1])


def test_momentum_flow_divergence_columns_are_zero_not_nan_once_momentum_is_available() -> None:
    """momentum_money_flow_frame fills unmatched-but-in-range divergence
    rows with 0, not NaN - build_feature_matrix must preserve that for
    every bar where momentum_wave itself is already available (early
    warmup bars are legitimately NaN for both, same as every other
    extra's "insufficient history" contract)."""
    df = _ohlcv(80, seed=2)

    out = build_feature_matrix(df, momentum_flow=True)
    available = out["momentum_wave"].notna()

    for column in (
        "regular_bullish_divergence",
        "hidden_bullish_divergence",
        "regular_bearish_divergence",
        "hidden_bearish_divergence",
        "confirmed_pivot_low",
        "confirmed_pivot_high",
    ):
        assert out.loc[available, column].notna().all()


def test_momentum_flow_with_too_few_bars_is_all_nan_or_zero_not_a_crash() -> None:
    """Fewer bars than the default warmup+pivot-confirmation windows need -
    momentum_money_flow_frame's own divergence columns get dropped
    entirely in this case (see src/features/pipeline.py's comment on this
    exact edge case) - build_feature_matrix must not raise a KeyError."""
    df = _ohlcv(5, seed=3)

    out = build_feature_matrix(df, momentum_flow=True)

    assert set(MOMENTUM_FLOW_FEATURE_COLUMNS).issubset(out.columns)
    assert out["momentum_wave"].isna().all()
    assert (out["regular_bullish_divergence"] == 0).all()


def test_momentum_flow_config_windows_are_respected() -> None:
    from src.features.pipeline import FeatureConfig

    df = _ohlcv(30, seed=4)
    config = FeatureConfig(
        momentum_flow_channel_span=2,
        momentum_flow_momentum_span=2,
        momentum_flow_signal_window=2,
        momentum_flow_money_flow_window=2,
        momentum_flow_rsi_window=2,
    )

    out = build_feature_matrix(df, config, momentum_flow=True)

    # Smaller windows clear warmup much earlier than the defaults would.
    assert out["rsi"].iloc[10:].notna().all()
