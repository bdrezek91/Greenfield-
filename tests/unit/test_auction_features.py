"""Footprint, Volume Profile, and anchored VWAP use the real trade tape."""

from __future__ import annotations

import json

import pandas as pd
import pytest

from src.data.normalized_event import normalize_bybit_event
from src.data.raw_event import parse_bybit_message
from src.features.auction import anchored_vwap_frame, footprint_frame, volume_profile


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
