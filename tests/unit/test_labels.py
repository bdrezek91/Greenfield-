"""Label formulas must match hand-computed values and leave trailing rows NaN."""

from __future__ import annotations

import pandas as pd
import pytest

from src.ml.labels import (
    direction_label,
    expected_r_label,
    forward_return_label,
    triple_barrier_outcome,
)


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


def _barrier_frame(rows: list[tuple[float, float, float]]) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "timestamp": pd.date_range("2024-01-01", periods=len(rows), freq="h", tz="UTC"),
            "high": [row[0] for row in rows],
            "low": [row[1] for row in rows],
            "close": [row[2] for row in rows],
        }
    )


def test_triple_barrier_long_profit_take_is_path_dependent() -> None:
    frame = _barrier_frame([(100, 100, 100), (103, 99.5, 102), (104, 101, 103)])
    result = triple_barrier_outcome(frame, index=0, side=1, atr=1, horizon_bars=2)
    assert result.barrier == "PROFIT_TAKE"
    assert result.exit_price == pytest.approx(102)
    assert result.gross_return == pytest.approx(0.02)
    assert result.label == 1
    assert result.label_end_time == frame.iloc[1]["timestamp"]


def test_triple_barrier_short_profit_and_vertical_exit() -> None:
    short = _barrier_frame([(100, 100, 100), (100.5, 97.5, 98), (99, 97, 98)])
    profit = triple_barrier_outcome(short, index=0, side=-1, atr=1, horizon_bars=2)
    assert profit.barrier == "PROFIT_TAKE"
    assert profit.exit_price == pytest.approx(98)
    assert profit.gross_return == pytest.approx(0.02)

    vertical = _barrier_frame([(100, 100, 100), (100.5, 99.5, 100), (101, 99.1, 100.5)])
    timeout = triple_barrier_outcome(vertical, index=0, side=1, atr=1, horizon_bars=2)
    assert timeout.barrier == "VERTICAL"
    assert timeout.exit_price == pytest.approx(100.5)
    assert timeout.label_end_time == vertical.iloc[2]["timestamp"]


def test_triple_barrier_same_bar_collision_fails_to_stop() -> None:
    frame = _barrier_frame([(100, 100, 100), (103, 98, 101), (102, 99, 100)])
    result = triple_barrier_outcome(frame, index=0, side=1, atr=1, horizon_bars=2)
    assert result.barrier == "STOP_LOSS"
    assert result.exit_price == pytest.approx(99)
    assert result.gross_return == pytest.approx(-0.01)
    assert result.label == 0


def test_triple_barrier_cost_and_input_validation() -> None:
    frame = _barrier_frame([(100, 100, 100), (100.3, 99.8, 100.1)])
    result = triple_barrier_outcome(
        frame,
        index=0,
        side=1,
        atr=1,
        horizon_bars=1,
        label_cost_return=0.002,
    )
    assert result.gross_return == pytest.approx(0.001)
    assert result.label == 0
    with pytest.raises(ValueError, match="side"):
        triple_barrier_outcome(frame, index=0, side=0, atr=1, horizon_bars=1)
    with pytest.raises(ValueError, match="complete"):
        triple_barrier_outcome(frame, index=1, side=1, atr=1, horizon_bars=1)
