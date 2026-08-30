from __future__ import annotations

import pandas as pd
import pytest

from src.research.binance_archive_baselines import (
    OOS_START,
    evaluate_event_signal,
    monthly_oos_bounds,
)


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
    assert result["execution_scenarios"]["maker_maker"]["mean_net_bps"] == pytest.approx(
        expected + 6
    )
    assert result["execution_scenarios"]["maker_taker"]["mean_net_bps"] == pytest.approx(
        expected + 3
    )
    assert result["execution_scenarios"]["taker_taker"]["mean_net_bps"] == pytest.approx(
        expected - 1
    )
    medium = result["post_only_sensitivity"]["base_timeout_medium_fill"]
    assert medium["any_fill_probability"] == pytest.approx(0.60)
    assert medium["expected_executed_fraction"] == pytest.approx(0.525)
    expected_gross = expected + 12
    assert medium["mean_expected_net_bps_per_opportunity"] == pytest.approx(
        (expected_gross - 9 - 2) * 0.525
    )
    assert medium["primary_exit_mode"] == "TAKER"
    assert medium["exit_execution_scenarios"]["maker_exit"][
        "mean_expected_net_bps_per_opportunity"
    ] == pytest.approx(
        (expected_gross - 6 - 2) * 0.525
    )


def test_event_baseline_requires_exact_future_clock() -> None:
    timestamps = pd.to_datetime([OOS_START, OOS_START + pd.Timedelta(minutes=1)])
    bars = pd.DataFrame({"timestamp": timestamps, "close": [100.0, 101.0]})
    signal = pd.DataFrame({"timestamp": [OOS_START], "side": [1]})

    result = evaluate_event_signal(bars, signal, horizon_minutes=5, cost_bps=12.0)

    assert result["event_count"] == 0
    assert result["mean_net_bps"] is None
    assert result["execution_scenarios"]["maker_maker"]["mean_net_bps"] is None
    assert (
        result["post_only_sensitivity"]["base_timeout_medium_fill"]
        ["mean_expected_net_bps_per_opportunity"]
        is None
    )


def test_monthly_oos_bounds_use_exact_second_half() -> None:
    june_start, june_end = monthly_oos_bounds("2026-06")
    july_start, july_end = monthly_oos_bounds("2026-07")

    assert june_start == pd.Timestamp("2026-06-16T00:00:00Z")
    assert june_end == pd.Timestamp("2026-07-01T00:00:00Z")
    assert july_start == OOS_START
    assert july_end == pd.Timestamp("2026-08-01T00:00:00Z")


def test_monthly_oos_bounds_reject_non_month_period() -> None:
    with pytest.raises(ValueError, match="invalid monthly period"):
        monthly_oos_bounds("2026-06-01")
