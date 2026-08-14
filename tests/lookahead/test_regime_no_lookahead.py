"""No indicator or regime label may use information from after its own row.

Per docs/BACKTESTING.md's lookahead protection requirement: a feature at
time t may only use information available up to t. The test here is
structural, not statistical: classify the SAME prefix of data twice - once
alone, once as part of a longer series with more bars appended after it -
and require every value up to the shared boundary to be bit-for-bit
identical. If any indicator peeked at future rows, appending more data
after the boundary would change values at or before it.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from src.regimes.classifier import RegimeConfig, classify_regimes
from src.regimes.indicators import adx, atr, moving_average_structure, realized_volatility


def _ohlc(n: int, seed: int = 0) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    close = 100 + np.cumsum(rng.normal(0.02, 0.6, size=n))
    ts = pd.date_range("2024-01-01", periods=n, freq="1h", tz="UTC")
    return pd.DataFrame(
        {"timestamp": ts, "high": close + 0.5, "low": close - 0.5, "close": close}
    )


@pytest.fixture
def full_and_truncated() -> tuple[pd.DataFrame, pd.DataFrame, int]:
    full = _ohlc(300)
    cutoff = 150
    truncated = full.iloc[:cutoff].reset_index(drop=True)
    return full, truncated, cutoff


def test_true_range_and_atr_unaffected_by_future_data(full_and_truncated) -> None:
    full, truncated, cutoff = full_and_truncated
    atr_full = atr(full, period=14).iloc[:cutoff]
    atr_truncated = atr(truncated, period=14)
    pd.testing.assert_series_equal(atr_full.reset_index(drop=True), atr_truncated)


def test_adx_unaffected_by_future_data(full_and_truncated) -> None:
    full, truncated, cutoff = full_and_truncated
    adx_full = adx(full, period=14).iloc[:cutoff]
    adx_truncated = adx(truncated, period=14)
    pd.testing.assert_series_equal(adx_full.reset_index(drop=True), adx_truncated)


def test_realized_volatility_unaffected_by_future_data(full_and_truncated) -> None:
    full, truncated, cutoff = full_and_truncated
    vol_full = realized_volatility(full, period=20).iloc[:cutoff]
    vol_truncated = realized_volatility(truncated, period=20)
    pd.testing.assert_series_equal(vol_full.reset_index(drop=True), vol_truncated)


def test_moving_average_structure_unaffected_by_future_data(full_and_truncated) -> None:
    full, truncated, cutoff = full_and_truncated
    ma_full = moving_average_structure(full, 20, 50).iloc[:cutoff]
    ma_truncated = moving_average_structure(truncated, 20, 50)
    pd.testing.assert_frame_equal(ma_full.reset_index(drop=True), ma_truncated)


def test_classify_regimes_unaffected_by_future_data(full_and_truncated) -> None:
    full, truncated, cutoff = full_and_truncated
    config = RegimeConfig(long_ma_period=50, vol_lookback=50)

    out_full = classify_regimes(full, config).iloc[:cutoff]
    out_truncated = classify_regimes(truncated, config)

    pd.testing.assert_series_equal(
        out_full["trend_regime"].reset_index(drop=True), out_truncated["trend_regime"]
    )
    pd.testing.assert_series_equal(
        out_full["vol_regime"].reset_index(drop=True), out_truncated["vol_regime"]
    )
