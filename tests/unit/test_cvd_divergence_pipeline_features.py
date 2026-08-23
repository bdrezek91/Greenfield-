"""build_feature_matrix's optional price/CVD divergence feature family
(Cycle 34 - continues Cycles 26-31's wiring of orphaned src/features/
modules, this time src.features.divergence's price_cvd_divergence_frame).
Unlike every other extra so far, this one is computed FROM the same raw
`trade_flow` frame already required for Cycle 26's `trade_flow` extra -
`cvd_divergence=True` without `trade_flow` must raise, not silently
produce nothing.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from src.features.pipeline import (
    CVD_DIVERGENCE_FEATURE_COLUMNS,
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


# Hand-crafted price/cvd series with a genuine regular-bullish divergence:
# a lower price low at index 8 (95 < 100 at index 2) paired with a higher
# CVD low (5 > -10) - price.py's/divergence.py's own pivot-confirmation
# logic (default left_bars=right_bars=2) confirms the index-2 pivot at
# row 4 and the index-8 pivot at row 10.
_PRICE = [105, 103, 100, 103, 105, 107, 103, 100, 95, 100, 103, 105]
_CVD = [0, -5, -10, -3, 2, 8, 3, -2, 5, 10, 15, 20]


def _trade_flow_with_divergence(ts: pd.Series) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "timestamp": ts,
            "max_source_timestamp": ts,
            "trade_vwap": _PRICE,
            "cvd": _CVD,
            "trade_delta": 1.0,
        }
    )


def test_omitting_cvd_divergence_leaves_output_unchanged() -> None:
    df = _ohlcv(60)
    out = build_feature_matrix(df)

    assert "cvd_regular_bullish_divergence" not in out.columns
    assert set(FEATURE_COLUMNS).issubset(out.columns)


def test_cvd_divergence_without_trade_flow_raises() -> None:
    df = _ohlcv(12)
    with pytest.raises(ValueError, match="trade_flow"):
        build_feature_matrix(df, cvd_divergence=True)


def test_cvd_divergence_columns_present_and_reflect_a_real_divergence() -> None:
    df = _ohlcv(12)
    trade_flow = _trade_flow_with_divergence(df["timestamp"])

    out = build_feature_matrix(df, trade_flow=trade_flow, cvd_divergence=True)

    assert set(CVD_DIVERGENCE_FEATURE_COLUMNS).issubset(out.columns)
    # Also still gets the plain trade_flow extra - independent, not mutually
    # exclusive.
    assert "cvd" in out.columns

    # No confirmation exists yet before row 4 (left_bars + right_bars).
    assert out["cvd_regular_bullish_divergence"].iloc[:4].isna().all()
    # The second (index-8) pivot, confirmed at row 10, is a genuine regular
    # bullish divergence: lower price low, higher CVD low than the first.
    assert out["cvd_regular_bullish_divergence"].iloc[10] == 1
    # The first (index-2) pivot, confirmed at row 4, has no prior pivot to
    # compare against yet.
    assert out["cvd_regular_bullish_divergence"].iloc[4] == 0


def test_cvd_divergence_never_leaks_a_pivot_not_yet_confirmed() -> None:
    """price_cvd_divergence_frame needs left_bars+right_bars of trailing
    data past a pivot to confirm it - the index-8 low pivot (which becomes
    the real divergence at row 10) isn't confirmable from only the first
    10 rows of trade_flow. Passing that truncated trade_flow must never
    make later bars (10, 11) show the divergence that would only appear
    once trade_flow eventually included the confirming rows - the as-of
    join must reflect only what was knowable at the time, never the
    future value a fuller frame would eventually produce."""
    df = _ohlcv(12)
    truncated_trade_flow = _trade_flow_with_divergence(df["timestamp"]).iloc[:10]

    out = build_feature_matrix(df, trade_flow=truncated_trade_flow, cvd_divergence=True)

    assert not (out["cvd_regular_bullish_divergence"].iloc[10:] == 1).any()
