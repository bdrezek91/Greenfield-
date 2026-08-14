"""Label formulas must match hand-computed values and leave trailing rows NaN."""

from __future__ import annotations

import pandas as pd
import pytest

from src.ml.labels import direction_label, expected_r_label, forward_return_label


def _df() -> pd.DataFrame:
    ts = pd.date_range("2024-01-01", periods=10, freq="1h", tz="UTC")
    close = pd.Series([100.0, 101, 102, 103, 104, 105, 106, 107, 108, 109])
    return pd.DataFrame({"timestamp": ts, "close": close})


def test_forward_return_hand_computed() -> None:
    df = _df()
    result = forward_return_label(df, horizon_bars=3)
    assert result["label"].iloc[0] == pytest.approx(103.0 / 100.0 - 1)
    assert result["label_end_time"].iloc[0] == df["timestamp"].iloc[3]


def test_forward_return_trailing_rows_are_nan() -> None:
    df = _df()
    result = forward_return_label(df, horizon_bars=3)
    assert result["label"].iloc[-3:].isna().all()
    assert result["label_end_time"].iloc[-3:].isna().all()


def test_direction_label_thresholds() -> None:
    ts = pd.date_range("2024-01-01", periods=4, freq="1h", tz="UTC")
    close = pd.Series([100.0, 100.5, 100.0, 99.0])
    df = pd.DataFrame({"timestamp": ts, "close": close})
    result = direction_label(df, horizon_bars=1, threshold=0.02)
    # bar0->bar1: +0.5% < 2% threshold -> flat (0)
    # bar1->bar2: -0.5% < 2% threshold -> flat (0)
    # bar2->bar3: -1% < 2% threshold -> flat (0)
    assert result["label"].iloc[0] == 0.0


def test_direction_label_up_and_down() -> None:
    ts = pd.date_range("2024-01-01", periods=3, freq="1h", tz="UTC")
    close = pd.Series([100.0, 110.0, 90.0])
    df = pd.DataFrame({"timestamp": ts, "close": close})
    result = direction_label(df, horizon_bars=1, threshold=0.01)
    assert result["label"].iloc[0] == 1.0  # +10%
    assert result["label"].iloc[1] == -1.0  # -18.2%


def test_expected_r_label_hand_computed() -> None:
    ts = pd.date_range("2024-01-01", periods=3, freq="1h", tz="UTC")
    close = pd.Series([100.0, 105.0, 95.0])
    df = pd.DataFrame({"timestamp": ts, "close": close})
    atr = pd.Series([2.0, 2.0, 2.0])
    result = expected_r_label(df, horizon_bars=1, atr=atr, atr_multiple=1.0)
    assert result["label"].iloc[0] == pytest.approx((105.0 - 100.0) / 2.0)


def test_expected_r_label_respects_atr_multiple() -> None:
    ts = pd.date_range("2024-01-01", periods=2, freq="1h", tz="UTC")
    close = pd.Series([100.0, 110.0])
    df = pd.DataFrame({"timestamp": ts, "close": close})
    atr = pd.Series([2.0, 2.0])
    result = expected_r_label(df, horizon_bars=1, atr=atr, atr_multiple=2.0)
    assert result["label"].iloc[0] == pytest.approx(10.0 / 4.0)
