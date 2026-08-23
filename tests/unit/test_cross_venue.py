from __future__ import annotations

import pandas as pd
import pytest

from src.features.cross_venue import cross_venue_series_frame, cross_venue_snapshot


def _quotes() -> pd.DataFrame:
    cutoff = pd.Timestamp("2026-01-01T00:00:10Z")
    return pd.DataFrame(
        {
            "timestamp": [cutoff - pd.Timedelta(seconds=1)] * 3,
            "max_source_timestamp": [cutoff - pd.Timedelta(seconds=1)] * 3,
            "exchange": ["bybit", "binance", "okx"],
            "canonical_instrument_id": ["BTC-USDT:PERP:USDT"] * 3,
            "mid_price": [100.0, 100.1, 102.0],
        }
    )


def test_cross_venue_snapshot_flags_price_outlier_and_reports_age() -> None:
    result = cross_venue_snapshot(
        _quotes(),
        canonical_instrument_id="BTC-USDT:PERP:USDT",
        as_of=pd.Timestamp("2026-01-01T00:00:10Z"),
        max_deviation_bps=50,
    )

    assert result["exchange"].tolist() == ["binance", "bybit", "okx"]
    assert result["cross_venue_median"].nunique() == 1
    assert result.loc[result["exchange"] == "okx", "is_price_outlier"].item() == 1
    assert (result["quote_age_ms"] == 1_000).all()


def test_snapshot_ignores_future_and_stale_quotes() -> None:
    quotes = _quotes()
    future = quotes.iloc[[0]].copy()
    future["exchange"] = "future"
    future["timestamp"] = pd.Timestamp("2026-01-01T00:00:11Z")
    future["max_source_timestamp"] = future["timestamp"]
    stale = quotes.iloc[[0]].copy()
    stale["exchange"] = "stale"
    stale["timestamp"] = pd.Timestamp("2026-01-01T00:00:00Z")
    stale["max_source_timestamp"] = stale["timestamp"]
    combined = pd.concat([quotes, future, stale], ignore_index=True)

    result = cross_venue_snapshot(
        combined,
        canonical_instrument_id="BTC-USDT:PERP:USDT",
        as_of=pd.Timestamp("2026-01-01T00:00:10Z"),
    )

    assert set(result["exchange"]) == {"bybit", "binance", "okx"}


def test_cross_venue_snapshot_fails_closed_on_causality_or_schema() -> None:
    quotes = _quotes()
    invalid = quotes.copy()
    invalid.loc[0, "max_source_timestamp"] = invalid.loc[0, "timestamp"] + pd.Timedelta(
        seconds=1
    )
    with pytest.raises(ValueError, match="future source"):
        cross_venue_snapshot(
            invalid,
            canonical_instrument_id="BTC-USDT:PERP:USDT",
            as_of=pd.Timestamp("2026-01-01T00:00:10Z"),
        )
    with pytest.raises(ValueError, match="timezone-aware"):
        cross_venue_snapshot(
            quotes,
            canonical_instrument_id="BTC-USDT:PERP:USDT",
            as_of=pd.Timestamp("2026-01-01"),
        )


def test_cross_venue_series_frame_reduces_each_as_of_to_one_summary_row() -> None:
    cutoff = pd.Timestamp("2026-01-01T00:00:10Z")
    as_of_timestamps = pd.Series([cutoff - pd.Timedelta(seconds=2), cutoff])

    series = cross_venue_series_frame(
        _quotes(),
        canonical_instrument_id="BTC-USDT:PERP:USDT",
        as_of_timestamps=as_of_timestamps,
        max_deviation_bps=50,
    )

    assert len(series) == 2
    # Before any quote has arrived (quotes are at cutoff - 1s): no venues.
    assert series.iloc[0]["cross_venue_count"] == 0
    assert pd.isna(series.iloc[0]["cross_venue_max_abs_deviation_bps"])
    # At the cutoff: all three venues, okx is the one outlier (102 vs a
    # ~100.1 median, well past the 50bps threshold).
    assert series.iloc[1]["cross_venue_count"] == 3
    assert series.iloc[1]["cross_venue_outlier_count"] == 1
    assert series.iloc[1]["cross_venue_max_abs_deviation_bps"] > 50


def test_cross_venue_series_frame_never_leaks_a_future_quote() -> None:
    """A per-row summary must reflect only quotes available at that row's
    own as_of - never a quote that arrives later in the walk, even though
    a later as_of in the same call does see it."""
    cutoff = pd.Timestamp("2026-01-01T00:00:10Z")
    as_of_timestamps = pd.Series([cutoff - pd.Timedelta(seconds=1, milliseconds=500), cutoff])

    series = cross_venue_series_frame(
        _quotes(),
        canonical_instrument_id="BTC-USDT:PERP:USDT",
        as_of_timestamps=as_of_timestamps,
    )

    assert series.iloc[0]["cross_venue_count"] == 0
    assert series.iloc[1]["cross_venue_count"] == 3
