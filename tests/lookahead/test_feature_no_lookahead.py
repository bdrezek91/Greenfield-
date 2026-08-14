"""No feature may use information from after its own row.

Same structural proof as tests/lookahead/test_regime_no_lookahead.py
(Phase 8): compute features on a data prefix alone vs. as part of a longer
series and require bit-identical values up to the shared boundary. If any
feature peeked at future rows, appending more data after the boundary
would change values at or before it.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from src.features.pipeline import FeatureConfig, build_feature_matrix


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


@pytest.fixture
def full_and_truncated() -> tuple[pd.DataFrame, pd.DataFrame, int]:
    full = _ohlcv(300)
    cutoff = 150
    truncated = full.iloc[:cutoff].reset_index(drop=True)
    return full, truncated, cutoff


def test_feature_matrix_unaffected_by_future_data(full_and_truncated) -> None:
    full, truncated, cutoff = full_and_truncated
    config = FeatureConfig(range_percentile_lookback=50)  # fits within the 150-row truncation

    fm_full = build_feature_matrix(full, config).iloc[:cutoff].drop(columns="timestamp")
    fm_truncated = build_feature_matrix(truncated, config).drop(columns="timestamp")

    pd.testing.assert_frame_equal(fm_full.reset_index(drop=True), fm_truncated)
