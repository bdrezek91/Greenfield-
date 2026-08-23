"""Footprint, Volume Profile, and anchored VWAP use the real trade tape."""

from __future__ import annotations

import json

import pandas as pd
import pytest

from src.data.normalized_event import normalize_bybit_event
from src.data.raw_event import parse_bybit_message
from src.features.auction import (
    anchored_vwap_frame,
    footprint_frame,
    rolling_volume_profile_frame,
    volume_profile,
)


def _rows():
    raw = parse_bybit_message(
        json.dumps(
            {
                "topic": "publicTrade.BTCUSDT",
                "type": "snapshot",
                "ts": 120_100,
                "data": [
                    {"T": 60_100, "s": "BTCUSDT", "S": "Sell", "v": "1", "p": "99", "i": "a"},
                    {"T": 60_200, "s": "BTCUSDT", "S": "Buy", "v": "4", "p": "100", "i": "b"},
                    {"T": 60_300, "s": "BTCUSDT", "S": "Buy", "v": "3", "p": "101", "i": "c"},
                    {"T": 60_400, "s": "BTCUSDT", "S": "Sell", "v": "1", "p": "101", "i": "d"},
                    {"T": 120_100, "s": "BTCUSDT", "S": "Buy", "v": "2", "p": "102", "i": "e"},
                ],
            },
            separators=(",", ":"),
        ),
        receive_ts_ns=120_200_000_000,
        receive_sequence=1,
        connection_id="c",
    )
    return list(normalize_bybit_event(raw))


def test_footprint_delta_diagonal_and_stacked_imbalance() -> None:
    frame = footprint_frame(
        _rows(), symbol="BTCUSDT", bucket_ms=60_000, price_tick="1", imbalance_ratio=3
    )
    first = frame.iloc[:3].set_index("price_level")

    assert first.loc[100.0, "delta"] == 4.0
    assert first.loc[101.0, "delta"] == 2.0
    assert first.loc[100.0, "diagonal_buy_ratio"] == 4.0
    assert first.loc[100.0, "stacked_buy_levels"] == 1
    assert (frame["max_source_timestamp"] <= frame["timestamp"]).all()


def test_volume_profile_expands_around_poc() -> None:
    footprint = pd.DataFrame(
        {"price_level": [98.0, 99.0, 100.0, 101.0, 102.0], "total_volume": [1, 3, 10, 5, 1]}
    )
    profile = volume_profile(footprint, value_area_fraction=0.70)

    assert profile.poc == 100.0
    assert profile.val == 100.0
    assert profile.vah == 101.0
    assert profile.total_volume == 20.0
    assert profile.value_area_volume == 15.0


def test_vwap_and_avwap_are_causal() -> None:
    full = anchored_vwap_frame(_rows(), symbol="BTCUSDT")
    anchored = anchored_vwap_frame(_rows(), symbol="BTCUSDT", anchor_ts_ms=120_000)

    assert full.iloc[-1]["vwap"] == pytest.approx((99 + 400 + 303 + 101 + 204) / 11)
    assert anchored.iloc[-1]["vwap"] == 102.0
    assert anchored.iloc[-1]["cumulative_volume"] == 2.0
    assert (full["max_source_timestamp"] <= full["timestamp"]).all()


def test_invalid_profile_fraction_is_rejected() -> None:
    with pytest.raises(ValueError, match="value_area_fraction"):
        volume_profile(
            pd.DataFrame({"price_level": [1], "total_volume": [1]}),
            value_area_fraction=0,
        )


def test_footprint_frame_includes_bucket_start_ms() -> None:
    """rolling_volume_profile_frame (below) needs a reliable bucket key -
    the frame's own `timestamp` is per-price-level (its receive_ts_ns can
    differ level to level within one bucket), so it cannot be reversed
    back into an exact bucket boundary the way `bucket_start_ms` can."""
    frame = footprint_frame(
        _rows(), symbol="BTCUSDT", bucket_ms=60_000, price_tick="1", imbalance_ratio=3
    )
    assert set(frame["bucket_start_ms"]) == {60_000, 120_000}


def _synthetic_footprint(bucket_volumes: list[dict[float, float]]) -> pd.DataFrame:
    """One dict per bucket: {price_level: total_volume}. Bucket N gets
    bucket_start_ms = N * 60_000 and timestamp = its own end + 1ms."""
    rows = []
    for bucket_index, levels in enumerate(bucket_volumes):
        bucket_start_ms = bucket_index * 60_000
        ts = pd.Timestamp(bucket_start_ms + 60_001, unit="ms", tz="UTC")
        for price, volume in levels.items():
            rows.append(
                {
                    "bucket_start_ms": bucket_start_ms,
                    "price_level": price,
                    "total_volume": volume,
                    "timestamp": ts,
                }
            )
    return pd.DataFrame(rows)


def test_rolling_volume_profile_skips_buckets_without_a_full_trailing_window() -> None:
    footprint = _synthetic_footprint(
        [{100.0: 10}, {101.0: 10}, {102.0: 10}, {103.0: 10}]
    )  # 4 buckets

    rolling = rolling_volume_profile_frame(footprint, window_buckets=3)

    # Only buckets 2 and 3 (0-indexed) have a full trailing window of 3.
    assert len(rolling) == 2


def test_rolling_volume_profile_only_uses_the_trailing_window_causally() -> None:
    footprint = _synthetic_footprint(
        [
            {100.0: 100},  # bucket 0: dominant volume, should age out of the window later
            {200.0: 1},  # bucket 1
            {200.0: 1},  # bucket 2
        ]
    )

    rolling = rolling_volume_profile_frame(footprint, window_buckets=2)

    # First emitted row covers buckets [0, 1] - bucket 0 still dominates.
    assert rolling.iloc[0]["poc"] == 100.0
    # Second emitted row covers buckets [1, 2] - bucket 0 has aged out.
    assert rolling.iloc[1]["poc"] == 200.0


def test_rolling_volume_profile_timestamp_matches_the_current_buckets_own_timestamp() -> None:
    footprint = _synthetic_footprint([{100.0: 10}, {101.0: 10}])

    rolling = rolling_volume_profile_frame(footprint, window_buckets=2)

    # window_buckets=2 needs both buckets to emit a row - the emitted row
    # is for bucket index 1 (bucket_start_ms=60_000), whose own timestamp
    # is 60_000 + 60_001 = 120_001ms, not bucket 0's.
    assert rolling.iloc[0]["timestamp"] == pd.Timestamp(120_001, unit="ms", tz="UTC")


def test_rolling_volume_profile_rejects_non_positive_window() -> None:
    with pytest.raises(ValueError, match="window_buckets"):
        rolling_volume_profile_frame(_synthetic_footprint([{100.0: 1}]), window_buckets=0)
