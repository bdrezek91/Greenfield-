"""build_feature_matrix's optional derivatives-context feature family
(Cycle 29 - continues Cycles 26-28's wiring of orphaned src/features/
modules, this time src.features.derivatives's derivatives_context_frame).
Same as-of-join pattern as trade_flow/l2_imbalance (Cycle 26): the caller
builds and passes an already point-in-time-aligned frame, not computed
here. Only the already-normalized/derived columns are joined, not the
frame's raw mark_return/oi_change/basis_bps/funding_rate/
funding_annualized_pct.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from src.features.derivatives import derivatives_context_frame
from src.features.pipeline import (
    DERIVATIVES_CONTEXT_FEATURE_COLUMNS,
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


def _derivatives_context(ts: pd.Series, rolling_window: int = 20) -> pd.DataFrame:
    rows = len(ts)
    trend = np.linspace(100, 110, rows)
    cycle = np.sin(np.arange(rows) / 5.0)
    raw = pd.DataFrame(
        {
            "timestamp": ts,
            "max_source_timestamp": ts,
            "mark_price": trend + cycle + 0.05,
            "index_price": trend + cycle,
            "open_interest": 1_000 + np.arange(rows) * 2 + cycle * 5,
            "funding_rate": 0.0001 + cycle * 0.00002,
        }
    )
    return derivatives_context_frame(raw, rolling_window=rolling_window)


def test_omitting_derivatives_context_leaves_output_unchanged() -> None:
    df = _ohlcv(60)
    out = build_feature_matrix(df)

    assert "derivatives_crowding_score" not in out.columns
    assert set(FEATURE_COLUMNS).issubset(out.columns)


def test_derivatives_context_adds_only_the_normalized_columns() -> None:
    df = _ohlcv(60, seed=1)
    context = _derivatives_context(df["timestamp"], rolling_window=20)

    out = build_feature_matrix(df, derivatives_context=context)

    assert set(DERIVATIVES_CONTEXT_FEATURE_COLUMNS).issubset(out.columns)
    # Raw/less-ML-ready columns from the same frame must NOT leak through.
    assert "mark_return" not in out.columns
    assert "basis_bps" not in out.columns
    assert "funding_annualized_pct" not in out.columns


def test_derivatives_context_features_are_nan_before_the_rolling_window_matures() -> None:
    df = _ohlcv(60, seed=2)
    context = _derivatives_context(df["timestamp"], rolling_window=20)

    out = build_feature_matrix(df, derivatives_context=context)

    # funding_zscore/basis_zscore need `rolling_window` bars of warmup in
    # derivatives_context_frame itself (rolling(window, min_periods=window)
    # matures at the window-th row, index `rolling_window - 1`).
    assert out["funding_zscore"].iloc[: 20 - 1].isna().all()
    assert out["funding_zscore"].iloc[20 - 1 :].notna().all()


def test_derivatives_context_is_as_of_joined_never_a_future_reading() -> None:
    df = _ohlcv(30, seed=3)
    full_context = _derivatives_context(df["timestamp"], rolling_window=10)
    # Only give the pipeline context up through bar 20 - later bars must
    # not see values that "arrived" after their own timestamp.
    partial_context = full_context.iloc[:21].copy()

    out = build_feature_matrix(df, derivatives_context=partial_context)

    assert (
        out["derivatives_crowding_score"].iloc[21:]
        == out["derivatives_crowding_score"].iloc[20]
    ).all()
