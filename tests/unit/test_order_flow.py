"""ATAS-like order-flow features remain causal and chunk-stable."""

from __future__ import annotations

import json

import pandas as pd
import pytest

from src.data.normalized_event import normalize_bybit_event
from src.data.raw_event import parse_bybit_message
from src.features.order_flow import (
    L2ImbalanceAccumulator,
    OrderFlowError,
    TradeFlowAccumulator,
    l2_imbalance_frame,
    trade_flow_frame,
)


def _normalized(message: dict, receive_ns: int, sequence: int):
    raw = parse_bybit_message(
        json.dumps(message, separators=(",", ":")),
        receive_ts_ns=receive_ns,
        receive_sequence=sequence,
        connection_id="c",
    )
    return list(normalize_bybit_event(raw))


def _trades():
    return _normalized(
        {
            "topic": "publicTrade.BTCUSDT",
            "type": "snapshot",
            "ts": 120_100,
            "data": [
                {"T": 60_100, "s": "BTCUSDT", "S": "Buy", "v": "2", "p": "100", "i": "a"},
                {"T": 60_200, "s": "BTCUSDT", "S": "Sell", "v": "0.5", "p": "102", "i": "b"},
                {"T": 120_100, "s": "BTCUSDT", "S": "Sell", "v": "1", "p": "101", "i": "c"},
            ],
        },
        120_200_000_000,
        1,
    )


def _book(message_type: str, update_id: int, receive_ns: int, bids, asks):
    return _normalized(
        {
            "topic": "orderbook.50.BTCUSDT",
            "type": message_type,
            "ts": receive_ns // 1_000_000,
            "cts": receive_ns // 1_000_000 - 1,
            "data": {"s": "BTCUSDT", "b": bids, "a": asks, "u": update_id, "seq": update_id * 10},
        },
        receive_ns,
        update_id,
    )


def test_trade_delta_cvd_and_vwap_use_aggressor_side() -> None:
    frame = trade_flow_frame(_trades(), symbol="BTCUSDT", bucket_ms=60_000)

    assert frame["buy_volume"].tolist() == [2.0, 0.0]
    assert frame["sell_volume"].tolist() == [0.5, 1.0]
    assert frame["trade_delta"].tolist() == [1.5, -1.0]
    assert frame["cvd"].tolist() == [1.5, 0.5]
    assert frame["trade_count"].tolist() == [2, 1]
    assert frame.loc[0, "trade_vwap"] == pytest.approx((200 + 51) / 2.5)
    assert (frame["max_source_timestamp"] <= frame["timestamp"]).all()


def test_trade_flow_is_identical_across_chunk_boundaries() -> None:
    rows = _trades()
    whole = TradeFlowAccumulator("BTCUSDT")
    expected = whole.update(rows) + whole.finalize()
    chunked = TradeFlowAccumulator("BTCUSDT")
    observed = []
    for row in rows:
        observed.extend(chunked.update([row]))
    observed.extend(chunked.finalize())
    pd.testing.assert_frame_equal(pd.DataFrame(expected), pd.DataFrame(observed))


def test_l2_snapshot_delta_features_and_chunk_stability() -> None:
    snapshot = _book(
        "snapshot",
        10,
        1_700_000_000_010_000_000,
        [["100", "3"], ["99", "2"]],
        [["101", "1"], ["102", "4"]],
    )
    delta = _book(
        "delta",
        11,
        1_700_000_000_020_000_000,
        [["100", "4"]],
        [["101", "0"], ["103", "2"]],
    )
    rows = snapshot + delta
    expected = l2_imbalance_frame(rows, symbol="BTCUSDT", depth_levels=2)
    accumulator = L2ImbalanceAccumulator("BTCUSDT", depth_levels=2)
    output = []
    for row in rows:
        output.extend(accumulator.update([row]))
    output.extend(accumulator.finalize())
    observed = pd.DataFrame(output)

    pd.testing.assert_frame_equal(expected, observed)
    assert expected["book_update_id"].tolist() == [10, 11]
    assert expected.loc[0, "book_imbalance"] == pytest.approx(0.0)
    assert expected.loc[1, "best_ask"] == 102.0
    assert expected.loc[1, "book_imbalance"] == pytest.approx((6 - 6) / 12)
    assert (expected["max_source_timestamp"] <= expected["timestamp"]).all()


def test_l2_gap_invalidates_state() -> None:
    snapshot = _book(
        "snapshot", 10, 1_700_000_000_010_000_000, [["100", "1"]], [["101", "1"]]
    )
    gap = _book(
        "delta", 12, 1_700_000_000_020_000_000, [["100", "2"]], []
    )
    accumulator = L2ImbalanceAccumulator("BTCUSDT")
    accumulator.update(snapshot)
    accumulator.update(gap)
    with pytest.raises(OrderFlowError, match="gap"):
        accumulator.finalize()


def test_wrong_stream_is_rejected() -> None:
    with pytest.raises(OrderFlowError, match="only trade"):
        TradeFlowAccumulator("BTCUSDT").update(
            _book(
                "snapshot", 1, 1_700_000_000_010_000_000, [["100", "1"]], [["101", "1"]]
            )
        )
