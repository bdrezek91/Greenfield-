"""build_feature_matrix's optional trade-flow/L2-imbalance features
(Cycle 26 - closes the gap flagged by an autonomous survey: src.features.
order_flow's TradeFlowAccumulator/L2ImbalanceAccumulator were fully built
and tested but never reachable from build_feature_matrix, the single
entry point src.strategies.ml_filtered and research code use). Same
opt-in-only, as-of-join contract as test_funding_oi_features.py's
funding/open_interest tests - independent of each other and of
funding/open_interest.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from src.features.pipeline import (
    FEATURE_COLUMNS,
    L2_IMBALANCE_FEATURE_COLUMNS,
    TRADE_FLOW_FEATURE_COLUMNS,
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


def test_omitting_trade_flow_and_l2_leaves_output_unchanged() -> None:
    df = _ohlcv(60)
    out = build_feature_matrix(df)

    assert "cvd" not in out.columns
    assert "trade_delta" not in out.columns
    assert "book_imbalance" not in out.columns
    assert "spread" not in out.columns
    assert set(FEATURE_COLUMNS).issubset(out.columns)


def test_trade_flow_and_l2_imbalance_are_independent_extras() -> None:
    """Passing one without the other must work - they come from genuinely
    different Silver streams (trades vs order book), unlike
    funding/open_interest which this module treats as an all-or-nothing
    pair."""
    df = _ohlcv(10)
    trade_flow = pd.DataFrame(
        {
            "timestamp": df["timestamp"],
            "cvd": np.arange(10, dtype=float),
            "trade_delta": np.ones(10),
        }
    )

    out_trade_only = build_feature_matrix(df, trade_flow=trade_flow)
    assert set(TRADE_FLOW_FEATURE_COLUMNS).issubset(out_trade_only.columns)
    assert "book_imbalance" not in out_trade_only.columns

    l2_imbalance = pd.DataFrame(
        {
            "timestamp": df["timestamp"],
            "book_imbalance": np.linspace(-1, 1, 10),
            "spread": np.full(10, 0.5),
        }
    )
    out_l2_only = build_feature_matrix(df, l2_imbalance=l2_imbalance)
    assert set(L2_IMBALANCE_FEATURE_COLUMNS).issubset(out_l2_only.columns)
    assert "cvd" not in out_l2_only.columns


def test_passing_both_adds_both_column_sets() -> None:
    df = _ohlcv(10)
    trade_flow = pd.DataFrame(
        {"timestamp": df["timestamp"], "cvd": np.arange(10, dtype=float), "trade_delta": 1.0}
    )
    l2_imbalance = pd.DataFrame(
        {"timestamp": df["timestamp"], "book_imbalance": 0.1, "spread": 0.5}
    )

    out = build_feature_matrix(df, trade_flow=trade_flow, l2_imbalance=l2_imbalance)

    assert set(TRADE_FLOW_FEATURE_COLUMNS).issubset(out.columns)
    assert set(L2_IMBALANCE_FEATURE_COLUMNS).issubset(out.columns)


def test_cvd_before_first_reading_is_nan_not_a_future_value() -> None:
    df = _ohlcv(10)
    # Trade-flow history only starts partway through the bar series.
    trade_flow = pd.DataFrame(
        {
            "timestamp": [df["timestamp"].iloc[5]],
            "cvd": [42.0],
            "trade_delta": [3.0],
        }
    )

    out = build_feature_matrix(df, trade_flow=trade_flow)

    assert out["cvd"].iloc[:5].isna().all()
    assert (out["cvd"].iloc[5:] == 42.0).all()


def test_l2_features_as_of_joined_never_a_future_reading() -> None:
    df = _ohlcv(10)
    l2_imbalance = pd.DataFrame(
        {
            "timestamp": [df["timestamp"].iloc[3], df["timestamp"].iloc[7]],
            "book_imbalance": [0.2, -0.3],
            "spread": [0.5, 0.6],
        }
    )

    out = build_feature_matrix(df, l2_imbalance=l2_imbalance)

    assert out["book_imbalance"].iloc[:3].isna().all()
    assert (out["book_imbalance"].iloc[3:7] == 0.2).all()
    assert (out["book_imbalance"].iloc[7:] == -0.3).all()
