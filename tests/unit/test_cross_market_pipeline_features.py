"""build_feature_matrix's optional cross-market-context feature family
(Cycle 30 - continues Cycles 26-29's wiring of orphaned src/features/
modules, this time src.features.cross_market's cross_market_context_frame).
Same as-of-join pattern as trade_flow/derivatives_context, but the source
frame is LONG-format (multiple assets per timestamp) - the caller must
pre-filter it to df's own asset before passing it in.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from src.features.cross_market import cross_market_context_frame
from src.features.pipeline import (
    CROSS_MARKET_FEATURE_COLUMNS,
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


def _multi_asset_context(ts: pd.Series, rolling_window: int = 5) -> pd.DataFrame:
    rows = []
    n = len(ts)
    rng = np.random.default_rng(7)
    prices = {
        "BTC": 100 + np.cumsum(rng.normal(0, 0.5, size=n)),
        "ETH": 50 + np.cumsum(rng.normal(0, 0.4, size=n)),
        "SOL": 20 + np.cumsum(rng.normal(0, 0.3, size=n)),
    }
    for index, timestamp in enumerate(ts):
        for asset, series in prices.items():
            spot = float(series[index])
            rows.append(
                {
                    "timestamp": timestamp,
                    "max_source_timestamp": timestamp,
                    "asset": asset,
                    "spot_price": spot,
                    "perpetual_price": spot * 1.0005,
                }
            )
    return cross_market_context_frame(pd.DataFrame(rows), rolling_window=rolling_window)


def test_omitting_cross_market_context_leaves_output_unchanged() -> None:
    df = _ohlcv(60)
    out = build_feature_matrix(df)

    assert "relative_strength_log_return" not in out.columns
    assert set(FEATURE_COLUMNS).issubset(out.columns)


def test_cross_market_context_must_be_pre_filtered_to_one_asset() -> None:
    """build_feature_matrix has no `symbol` parameter - passing the raw,
    multi-asset frame would silently as-of join whichever asset's row
    happens to sort first for a given timestamp, which is exactly the
    kind of ambiguity this function refuses to guess through elsewhere."""
    df = _ohlcv(30, seed=1)
    context = _multi_asset_context(df["timestamp"], rolling_window=5)
    btc_only = context[context["asset"] == "BTC"].drop(columns="asset")

    out = build_feature_matrix(df, cross_market_context=btc_only)

    assert set(CROSS_MARKET_FEATURE_COLUMNS).issubset(out.columns)
    assert "spot_return" not in out.columns
    assert "benchmark_return" not in out.columns


def test_cross_market_context_features_are_nan_before_the_rolling_window_matures() -> None:
    df = _ohlcv(30, seed=2)
    context = _multi_asset_context(df["timestamp"], rolling_window=5)
    eth_only = context[context["asset"] == "ETH"].drop(columns="asset")

    out = build_feature_matrix(df, cross_market_context=eth_only)

    # Correlation needs `rolling_window` periods of returns, and returns
    # themselves need one extra prior bar (pct_change) - matures at index
    # `rolling_window`, not `rolling_window - 1`.
    assert out["benchmark_rolling_correlation"].iloc[:5].isna().all()
    assert out["benchmark_rolling_correlation"].iloc[5:].notna().all()


def test_cross_market_context_is_as_of_joined_never_a_future_reading() -> None:
    df = _ohlcv(20, seed=3)
    context = _multi_asset_context(df["timestamp"], rolling_window=5)
    sol_only = context[context["asset"] == "SOL"].drop(columns="asset")
    partial = sol_only.iloc[:12].copy()

    out = build_feature_matrix(df, cross_market_context=partial)

    assert (
        out["relative_strength_log_return"].iloc[12:]
        == out["relative_strength_log_return"].iloc[11]
    ).all()
