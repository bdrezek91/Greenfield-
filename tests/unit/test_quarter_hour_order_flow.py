from pathlib import Path

import pandas as pd
import pytest

from src.research.quarter_hour_order_flow import quarter_hour_signal


def _bars() -> pd.DataFrame:
    timestamps = pd.date_range("2026-07-01T00:01:00Z", periods=46, freq="1min")
    frame = pd.DataFrame(
        {
            "timestamp": timestamps,
            "close": range(100, 146),
            "buy_volume": 5.0,
            "sell_volume": 5.0,
        }
    )
    for timestamp, buy, sell in (
        ("2026-07-01T00:01:00Z", 9.0, 1.0),
        ("2026-07-01T00:16:00Z", 8.0, 2.0),
        ("2026-07-01T00:31:00Z", 1.0, 9.0),
        ("2026-07-01T00:46:00Z", 2.0, 8.0),
    ):
        mask = frame["timestamp"] == pd.Timestamp(timestamp)
        frame.loc[mask, ["buy_volume", "sell_volume"]] = [buy, sell]
    return frame


def test_signal_uses_bar_ending_after_true_quarter_hour_open() -> None:
    signal, threshold = quarter_hour_signal(
        _bars(),
        period_start=pd.Timestamp("2026-07-01T00:00:00Z"),
        training_end=pd.Timestamp("2026-07-01T00:31:00Z"),
    )

    assert signal["timestamp"].tolist() == [
        pd.Timestamp("2026-07-01T00:01:00Z"),
        pd.Timestamp("2026-07-01T00:16:00Z"),
        pd.Timestamp("2026-07-01T00:31:00Z"),
        pd.Timestamp("2026-07-01T00:46:00Z"),
    ]
    assert threshold == pytest.approx(0.76)
    assert signal["side"].tolist() == [1, 0, -1, 0]


def test_oos_values_cannot_change_training_threshold() -> None:
    bars = _bars()
    kwargs = {
        "period_start": pd.Timestamp("2026-07-01T00:00:00Z"),
        "training_end": pd.Timestamp("2026-07-01T00:31:00Z"),
    }
    _, original = quarter_hour_signal(bars, **kwargs)
    bars.loc[bars["timestamp"] >= kwargs["training_end"], "buy_volume"] = 10_000.0
    _, changed = quarter_hour_signal(bars, **kwargs)

    assert changed == original


def test_signal_rejects_missing_or_degenerate_training_data() -> None:
    with pytest.raises(ValueError, match="missing columns"):
        quarter_hour_signal(
            pd.DataFrame({"timestamp": []}),
            period_start=pd.Timestamp("2026-07-01T00:00:00Z"),
            training_end=pd.Timestamp("2026-07-02T00:00:00Z"),
        )
    with pytest.raises(ValueError, match="threshold"):
        quarter_hour_signal(
            pd.DataFrame(
                {
                    "timestamp": [pd.Timestamp("2026-07-01T00:01:00Z")],
                    "buy_volume": [1.0],
                    "sell_volume": [1.0],
                }
            ),
            period_start=pd.Timestamp("2026-07-01T00:00:00Z"),
            training_end=pd.Timestamp("2026-07-02T00:00:00Z"),
        )


def test_preregistration_exists() -> None:
    assert Path("docs/PREREGISTRATION_QUARTER_HOUR_ORDER_FLOW_V0.md").exists()
