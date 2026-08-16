"""build_feature_matrix's optional funding/open-interest features: opt-in
only (no behavior change when omitted), and as-of joined (never a future
reading).
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from src.features.pipeline import EXTENDED_FEATURE_COLUMNS, FEATURE_COLUMNS, build_feature_matrix


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


def test_omitting_funding_and_oi_leaves_output_unchanged() -> None:
    df = _ohlcv(60)
    out = build_feature_matrix(df)

    assert "funding_rate" not in out.columns
    assert "oi_change" not in out.columns
    assert set(FEATURE_COLUMNS).issubset(out.columns)


def test_passing_both_adds_the_extended_columns() -> None:
    df = _ohlcv(60)
    funding = pd.DataFrame(
        {
            "timestamp": pd.date_range("2024-01-01", periods=8, freq="8h", tz="UTC"),
            "funding_rate": [0.0001 * i for i in range(8)],
        }
    )
    open_interest = pd.DataFrame(
        {"timestamp": df["timestamp"], "open_interest": 1000.0 + np.arange(60)}
    )

    out = build_feature_matrix(df, funding=funding, open_interest=open_interest)

    assert set(EXTENDED_FEATURE_COLUMNS).issubset(out.columns)


def test_funding_rate_before_first_reading_is_nan_not_a_future_value() -> None:
    df = _ohlcv(10)
    # Funding history only starts partway through the bar series.
    funding = pd.DataFrame(
        {
            "timestamp": [df["timestamp"].iloc[5]],
            "funding_rate": [0.0005],
        }
    )

    out = build_feature_matrix(df, funding=funding, open_interest=None)

    assert out["funding_rate"].iloc[:5].isna().all()
    assert (out["funding_rate"].iloc[5:] == 0.0005).all()


def test_oi_change_is_pct_change_of_as_of_joined_series() -> None:
    df = _ohlcv(5)
    open_interest = pd.DataFrame(
        {"timestamp": df["timestamp"], "open_interest": [1000.0, 1100.0, 1100.0, 990.0, 990.0]}
    )

    out = build_feature_matrix(df, funding=None, open_interest=open_interest)

    expected = pd.Series([1100.0, 1100.0, 990.0, 990.0]) / pd.Series(
        [1000.0, 1100.0, 1100.0, 990.0]
    ) - 1
    np.testing.assert_allclose(out["oi_change"].iloc[1:].to_numpy(), expected.to_numpy())
    assert pd.isna(out["oi_change"].iloc[0])
