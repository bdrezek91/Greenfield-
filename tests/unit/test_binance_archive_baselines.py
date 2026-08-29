from __future__ import annotations

import pandas as pd
import pytest

from src.research.binance_archive_baselines import OOS_START, evaluate_event_signal


def test_event_baseline_enters_next_minute_charges_cost_and_avoids_overlap() -> None:
    timestamps = pd.date_range(OOS_START, periods=20, freq="1min")
    bars = pd.DataFrame({"timestamp": timestamps, "close": range(100, 120)})
    signal = pd.DataFrame(
        {
            "timestamp": [timestamps[0], timestamps[1], timestamps[8]],
            "side": [1, 1, -1],
        }
    )

    result = evaluate_event_signal(bars, signal, horizon_minutes=5, cost_bps=12.0)

    assert result["event_count"] == 2
    expected = (((106 / 101 - 1) - (114 / 109 - 1)) / 2) * 10_000 - 12
    assert result["mean_net_bps"] == pytest.approx(expected)


def test_event_baseline_requires_exact_future_clock() -> None:
    timestamps = pd.to_datetime([OOS_START, OOS_START + pd.Timedelta(minutes=1)])
    bars = pd.DataFrame({"timestamp": timestamps, "close": [100.0, 101.0]})
    signal = pd.DataFrame({"timestamp": [OOS_START], "side": [1]})

    result = evaluate_event_signal(bars, signal, horizon_minutes=5, cost_bps=12.0)

    assert result["event_count"] == 0
    assert result["mean_net_bps"] is None
