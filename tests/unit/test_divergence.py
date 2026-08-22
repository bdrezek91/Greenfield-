from __future__ import annotations

import pandas as pd
import pytest

from src.features.divergence import (
    confirmed_divergence_frame,
    price_cvd_divergence_frame,
)


def _frame(prices: list[float], oscillator: list[float]) -> pd.DataFrame:
    timestamps = pd.date_range("2026-01-01", periods=len(prices), freq="min", tz="UTC")
    return pd.DataFrame(
        {
            "timestamp": timestamps,
            "max_source_timestamp": timestamps,
            "price": prices,
            "oscillator": oscillator,
        }
    )


def test_regular_bullish_divergence_is_emitted_after_confirmation() -> None:
    frame = _frame(
        [10, 9, 8, 9, 10, 9, 7, 9, 10],
        [0, -1, -2, -1, 0, -1, -1, -1, 0],
    )

    result = confirmed_divergence_frame(
        frame, price_col="price", oscillator_col="oscillator", left_bars=1, right_bars=1
    )

    signal = result.loc[result["regular_bullish_divergence"] == 1].iloc[0]
    assert signal["timestamp"] == frame.loc[7, "timestamp"]
    assert signal["timestamp"] > frame.loc[6, "timestamp"]
    assert signal["confirmed_pivot_low"] == 1
    assert signal["pivot_age_bars"] == 1


def test_divergence_result_does_not_change_when_future_rows_are_appended() -> None:
    frame = _frame(
        [10, 9, 8, 9, 10, 9, 7, 9, 10, 11, 8, 12],
        [0, -1, -2, -1, 0, -1, -1, -1, 0, 1, -1, 2],
    )
    prefix = frame.iloc[:9]

    short = confirmed_divergence_frame(
        prefix, price_col="price", oscillator_col="oscillator", left_bars=1, right_bars=1
    )
    full = confirmed_divergence_frame(
        frame, price_col="price", oscillator_col="oscillator", left_bars=1, right_bars=1
    )

    pd.testing.assert_frame_equal(short, full.loc[full["timestamp"] <= short["timestamp"].max()])


def test_divergence_configuration_and_schema_fail_closed() -> None:
    frame = _frame([1, 2, 1], [0, 1, 0])
    with pytest.raises(ValueError, match="positive"):
        confirmed_divergence_frame(
            frame, price_col="price", oscillator_col="oscillator", left_bars=0
        )
    with pytest.raises(ValueError, match="missing columns"):
        confirmed_divergence_frame(
            frame.drop(columns="oscillator"),
            price_col="price",
            oscillator_col="oscillator",
        )


def test_price_cvd_is_an_explicit_independent_confirmation_family() -> None:
    frame = _frame(
        [10, 9, 8, 9, 10, 9, 7, 9, 10],
        [0, -1, -2, -1, 0, -1, -1, -1, 0],
    ).rename(columns={"price": "trade_vwap", "oscillator": "cvd"})

    result = price_cvd_divergence_frame(frame, left_bars=1, right_bars=1)

    assert result["cvd_regular_bullish_divergence"].sum() == 1
    assert "regular_bullish_divergence" not in result
    signal = result.loc[result["cvd_regular_bullish_divergence"] == 1].iloc[0]
    assert signal["timestamp"] == frame.loc[7, "timestamp"]
