"""Liquidity interaction features use causal tape and exact L2 size changes."""

from __future__ import annotations

import json

import pandas as pd
import pytest

from src.data.normalized_event import normalize_bybit_event
from src.data.raw_event import parse_bybit_message
from src.features.interaction import (
    BookLiquidityAccumulator,
    TradeInteractionAccumulator,
    book_liquidity_change_frame,
    trade_interaction_frame,
)
from src.features.order_flow import OrderFlowError


def _rows(message: dict, receive_ns: int, sequence: int):
    return list(
        normalize_bybit_event(
            parse_bybit_message(
                json.dumps(message, separators=(",", ":")),
                receive_ts_ns=receive_ns,
                receive_sequence=sequence,
                connection_id="c",
            )
        )
    )


def _book(kind: str, update: int, receive_ns: int, bids, asks):
    return _rows(
        {
            "topic": "orderbook.50.BTCUSDT",
            "type": kind,
            "ts": receive_ns // 1_000_000,
            "data": {"s": "BTCUSDT", "b": bids, "a": asks, "u": update, "seq": update},
        },
        receive_ns,
        update,
    )


def test_cancellation_addition_and_replenishment_are_size_deltas() -> None:
    rows = (
        _book("snapshot", 10, 1_700_000_000_010_000_000, [["100", "5"]], [["101", "4"]])
        + _book("delta", 11, 1_700_000_000_020_000_000, [["100", "2"]], [["101", "6"]])
        + _book("delta", 12, 1_700_000_000_030_000_000, [["100", "4"]], [])
    )
    frame = book_liquidity_change_frame(rows, symbol="BTCUSDT")

    assert frame.loc[1, "bid_cancelled"] == 3.0
    assert frame.loc[1, "ask_added"] == 2.0
    assert frame.loc[2, "bid_added"] == 2.0
    assert frame.loc[2, "bid_replenished"] == 2.0
    assert (frame["max_source_timestamp"] <= frame["timestamp"]).all()


def test_book_gap_fails_closed() -> None:
    rows = _book("snapshot", 10, 10_000_000_000, [["100", "1"]], [["101", "1"]])
    rows += _book("delta", 12, 12_000_000_000, [["100", "2"]], [])
    with pytest.raises(OrderFlowError, match="gap"):
        book_liquidity_change_frame(rows, symbol="BTCUSDT")


def test_book_liquidity_is_stable_when_one_raw_event_crosses_chunks() -> None:
    rows = _book("snapshot", 10, 1_700_000_000_010_000_000, [["100", "5"]], [["101", "4"]]) + _book(
        "delta", 11, 1_700_000_000_020_000_000, [["100", "2"]], [["101", "6"]]
    )
    expected = book_liquidity_change_frame(rows, symbol="BTCUSDT")
    accumulator = BookLiquidityAccumulator("BTCUSDT")
    observed = []
    for row in rows:
        observed.extend(accumulator.update([row]))
    observed.extend(accumulator.finalize())

    pd.testing.assert_frame_equal(pd.DataFrame(observed), expected)


def test_sweep_absorption_and_exhaustion_rules() -> None:
    trades = _rows(
        {
            "topic": "publicTrade.BTCUSDT",
            "type": "snapshot",
            "ts": 180_000,
            "data": [
                {"T": 60_100, "s": "BTCUSDT", "S": "Buy", "v": "2", "p": "100", "i": "a"},
                {"T": 60_200, "s": "BTCUSDT", "S": "Buy", "v": "3", "p": "101", "i": "b"},
                {"T": 60_300, "s": "BTCUSDT", "S": "Sell", "v": "1", "p": "100", "i": "c"},
                {"T": 120_100, "s": "BTCUSDT", "S": "Buy", "v": "1", "p": "102", "i": "d"},
                {"T": 120_200, "s": "BTCUSDT", "S": "Sell", "v": "2", "p": "102", "i": "e"},
            ],
        },
        180_100_000_000,
        1,
    )
    frame = trade_interaction_frame(trades, symbol="BTCUSDT", bucket_ms=60_000, price_tick="1")

    assert frame.loc[0, "buy_sweep"] == 1
    assert frame.loc[0, "buy_sweep_levels"] == 2
    assert frame.loc[1, "buy_exhaustion"] == 1
    assert frame.loc[1, "sell_absorption"] == 1
    assert (frame["max_source_timestamp"] <= frame["timestamp"]).all()


def test_trade_interaction_accumulator_is_chunk_stable() -> None:
    trades = _rows(
        {
            "topic": "publicTrade.BTCUSDT",
            "type": "snapshot",
            "ts": 180_000,
            "data": [
                {"T": 60_100, "s": "BTCUSDT", "S": "Buy", "v": "2", "p": "100", "i": "a"},
                {"T": 60_200, "s": "BTCUSDT", "S": "Buy", "v": "3", "p": "101", "i": "b"},
                {"T": 120_100, "s": "BTCUSDT", "S": "Buy", "v": "1", "p": "102", "i": "c"},
                {"T": 120_200, "s": "BTCUSDT", "S": "Sell", "v": "2", "p": "102", "i": "d"},
            ],
        },
        180_100_000_000,
        1,
    )
    expected = trade_interaction_frame(trades, symbol="BTCUSDT", bucket_ms=60_000, price_tick="1")
    accumulator = TradeInteractionAccumulator("BTCUSDT", bucket_ms=60_000, price_tick="1")
    actual = pd.DataFrame(
        accumulator.update(trades[:2])
        + accumulator.update(trades[2:3])
        + accumulator.update(trades[3:])
        + accumulator.finalize()
    )

    pd.testing.assert_frame_equal(actual, expected)
