from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from src.features.cross_market import cross_market_context_frame


def _frame(periods: int = 6) -> pd.DataFrame:
    timestamps = pd.date_range("2026-01-01", periods=periods, freq="h", tz="UTC")
    rows = []
    prices = {
        "BTC": [100, 101, 102, 103, 104, 105],
        "ETH": [50, 51, 53, 52, 55, 57],
        "SOL": [20, 19, 21, 22, 21, 23],
    }
    for index, timestamp in enumerate(timestamps):
        for asset, series in prices.items():
            spot = float(series[index])
            rows.append(
                {
                    "timestamp": timestamp,
                    "max_source_timestamp": timestamp
                    - pd.Timedelta(milliseconds={"BTC": 30, "ETH": 20, "SOL": 10}[asset]),
                    "asset": asset,
                    "spot_price": spot,
                    "perpetual_price": spot * (1.001 if asset == "BTC" else 0.999),
                }
            )
    return pd.DataFrame(rows)


def test_builds_causal_relative_strength_basis_and_market_context() -> None:
    result = cross_market_context_frame(_frame(), rolling_window=3)

    final = result.loc[result["timestamp"] == result["timestamp"].max()].set_index("asset")
    assert list(final.index) == ["BTC", "ETH", "SOL"]
    assert final.loc["BTC", "spot_perpetual_basis_bps"] == pytest.approx(10)
    assert final.loc["ETH", "spot_perpetual_basis_bps"] == pytest.approx(-10)
    assert final.loc["BTC", "relative_strength_log_return"] == pytest.approx(0)
    expected_eth_strength = np.log(57 / 53) - np.log(105 / 102)
    assert final.loc["ETH", "relative_strength_log_return"] == pytest.approx(expected_eth_strength)
    assert final.loc["ETH", "cross_sectional_return_rank"] == pytest.approx(2 / 3)
    assert final.loc["SOL", "cross_sectional_return_rank"] == 1.0
    assert final.loc["BTC", "market_breadth_positive_fraction"] == 1.0
    assert final.loc["SOL", "cross_asset_return_dispersion"] > 0
    assert pd.notna(final.loc["ETH", "benchmark_rolling_correlation"])
    assert pd.notna(final.loc["ETH", "benchmark_lead_correlation"])
    assert final["max_source_timestamp"].nunique() == 1
    assert final["max_source_timestamp"].iloc[0] == final["timestamp"].iloc[0] - pd.Timedelta(
        milliseconds=10
    )


def test_first_timestamp_has_no_return_or_breadth_evidence() -> None:
    result = cross_market_context_frame(_frame(), rolling_window=3)
    first = result.loc[result["timestamp"] == result["timestamp"].min()]

    assert first["spot_return"].isna().all()
    assert first["market_breadth_positive_fraction"].isna().all()
    assert first["cross_asset_return_dispersion"].isna().all()


def test_future_price_changes_cannot_rewrite_earlier_context() -> None:
    frame = _frame()
    baseline = cross_market_context_frame(frame, rolling_window=3)
    changed = frame.copy()
    final_timestamp = changed["timestamp"].max()
    changed.loc[changed["timestamp"] == final_timestamp, "spot_price"] *= 10
    changed.loc[changed["timestamp"] == final_timestamp, "perpetual_price"] *= 10

    revised = cross_market_context_frame(changed, rolling_window=3)
    cutoff = final_timestamp - pd.Timedelta(hours=1)
    pd.testing.assert_frame_equal(
        baseline.loc[baseline["timestamp"] <= cutoff].reset_index(drop=True),
        revised.loc[revised["timestamp"] <= cutoff].reset_index(drop=True),
    )


def test_rejects_future_sources_duplicates_incomplete_panels_and_bad_prices() -> None:
    frame = _frame()
    future = frame.copy()
    future.loc[0, "max_source_timestamp"] = future.loc[0, "timestamp"] + pd.Timedelta(seconds=1)
    with pytest.raises(ValueError, match="future source"):
        cross_market_context_frame(future, rolling_window=3)

    with pytest.raises(ValueError, match="duplicate"):
        cross_market_context_frame(pd.concat([frame, frame.iloc[[0]]]), rolling_window=3)

    incomplete = frame.drop(index=0)
    with pytest.raises(ValueError, match="incomplete"):
        cross_market_context_frame(incomplete, rolling_window=3)

    bad = frame.copy()
    bad.loc[0, "spot_price"] = 0
    with pytest.raises(ValueError, match="positive"):
        cross_market_context_frame(bad, rolling_window=3)


def test_rejects_missing_benchmark_small_universe_and_invalid_configuration() -> None:
    frame = _frame()
    with pytest.raises(ValueError, match="benchmark is absent"):
        cross_market_context_frame(frame, benchmark_asset="XRP", rolling_window=3)
    with pytest.raises(ValueError, match="at least two assets"):
        cross_market_context_frame(frame.loc[frame["asset"] == "BTC"], rolling_window=3)
    with pytest.raises(ValueError, match="at least 3"):
        cross_market_context_frame(frame, rolling_window=2)


def test_empty_input_preserves_contract() -> None:
    empty = _frame().iloc[0:0]
    result = cross_market_context_frame(empty, rolling_window=3)

    assert result.empty
    assert "benchmark_lead_correlation" in result.columns
