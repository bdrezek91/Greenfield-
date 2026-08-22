from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from src.features.momentum_flow import momentum_money_flow_frame


def _candles(rows: int = 180) -> pd.DataFrame:
    timestamp = pd.date_range("2026-01-01", periods=rows, freq="min", tz="UTC")
    trend = np.linspace(100, 115, rows)
    cycle = np.sin(np.arange(rows) / 3.0) * 2.0
    close = trend + cycle
    return pd.DataFrame(
        {
            "timestamp": timestamp,
            "max_source_timestamp": timestamp,
            "high": close + 0.8,
            "low": close - 0.8,
            "close": close,
            "volume": 10 + np.cos(np.arange(rows) / 5.0),
        }
    )


def test_independent_momentum_money_flow_has_finite_causal_outputs() -> None:
    result = momentum_money_flow_frame(_candles())

    expected = {
        "momentum_wave",
        "momentum_signal",
        "momentum_histogram",
        "money_flow",
        "rsi",
        "regular_bullish_divergence",
        "hidden_bullish_divergence",
        "regular_bearish_divergence",
        "hidden_bearish_divergence",
    }
    assert expected.issubset(result.columns)
    assert not result.empty
    assert np.isfinite(result.select_dtypes(include="number").to_numpy()).all()
    assert (result["max_source_timestamp"] <= result["timestamp"]).all()
    assert result["money_flow"].between(-1, 1).all()
    assert result["rsi"].between(0, 100).all()


def test_momentum_money_flow_is_unchanged_by_appended_future_candles() -> None:
    candles = _candles()
    short = momentum_money_flow_frame(candles.iloc[:130])
    full = momentum_money_flow_frame(candles)
    comparable = full.loc[full["timestamp"] <= short["timestamp"].max()].reset_index(drop=True)

    pd.testing.assert_frame_equal(short.reset_index(drop=True), comparable)


def test_momentum_money_flow_rejects_invalid_input() -> None:
    candles = _candles(20)
    with pytest.raises(ValueError, match="missing columns"):
        momentum_money_flow_frame(candles.drop(columns="volume"))
    with pytest.raises(ValueError, match="exceed one"):
        momentum_money_flow_frame(candles, signal_window=1)
