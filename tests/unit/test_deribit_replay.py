"""Deribit snapshot/delta replay must never guess through sequence
uncertainty - the Deribit counterpart to test_bybit_replay.py/
test_binance_replay.py/test_okx_replay.py, adapted to Deribit's
self-bootstrapping change_id/prev_change_id protocol and its
[action, price, amount] book-level triplets (see src/data/deribit_replay.py's
module docstring for the differences).
"""

from __future__ import annotations

import json

import pytest

from src.data.deribit_adapter import (
    DeribitSequenceGap,
    DeribitSnapshotRequired,
    parse_deribit_message,
)
from src.data.deribit_replay import DeribitReplaySession, InvalidOrderBook, replay_deribit


def _book(
    message_type: str,
    change_id: int,
    previous: int | None = None,
    *,
    connection: str = "deribit-c1",
    bids: list[list] | None = None,
    asks: list[list] | None = None,
    instrument: str = "BTC-PERPETUAL",
    receive_ts_ns: int | None = None,
):
    data: dict = {
        "type": message_type,
        "timestamp": 1_700_000_000_000,
        "instrument_name": instrument,
        "change_id": change_id,
        "bids": [] if bids is None else bids,
        "asks": [] if asks is None else asks,
    }
    if previous is not None:
        data["prev_change_id"] = previous
    payload = {
        "jsonrpc": "2.0",
        "method": "subscription",
        "params": {"channel": f"book.{instrument}.100ms", "data": data},
    }
    return parse_deribit_message(
        json.dumps(payload, separators=(",", ":")),
        receive_ts_ns=receive_ts_ns or 1_700_000_000_001_000_000 + change_id,
        receive_sequence=max(change_id, 1),
        connection_id=connection,
    )


def test_snapshot_then_delta_rebuilds_exact_decimal_book() -> None:
    session = DeribitReplaySession()
    session.apply(
        _book(
            "snapshot",
            100,
            bids=[["new", "100.10", "2"], ["new", "100.00", "3"]],
            asks=[["new", "100.20", "4"]],
        )
    )
    session.apply(
        _book(
            "change",
            101,
            100,
            bids=[["delete", "100.10", "0"], ["new", "100.05", "7"]],
            asks=[["change", "100.20", "6"]],
        )
    )

    report = session.report()
    book = report.orderbooks["BTC-PERPETUAL"]
    assert book.change_id == 101
    assert book.best_bid == "100.05"
    assert book.best_ask == "100.20"
    assert book.bid_levels == 2


def test_delta_before_snapshot_is_rejected() -> None:
    session = DeribitReplaySession()
    with pytest.raises(DeribitSnapshotRequired):
        session.apply(_book("change", 101, 100, bids=[["new", "100", "1"]]))


def test_gap_after_bootstrap_raises() -> None:
    session = DeribitReplaySession()
    session.apply(
        _book("snapshot", 100, bids=[["new", "100", "1"]], asks=[["new", "101", "1"]])
    )
    session.apply(_book("change", 101, 100, bids=[["new", "100", "2"]]))

    with pytest.raises(DeribitSequenceGap):
        session.apply(_book("change", 103, 102))  # expected prev_change_id=101


def test_delete_action_removes_the_level_regardless_of_prior_size() -> None:
    session = DeribitReplaySession()
    session.apply(
        _book(
            "snapshot",
            100,
            bids=[["new", "100", "1"], ["new", "99", "1"]],
            asks=[["new", "101", "1"]],
        )
    )
    session.apply(_book("change", 101, 100, bids=[["delete", "100", "0"]]))

    report = session.report()
    book = report.orderbooks["BTC-PERPETUAL"]
    assert book.best_bid == "99"  # "100" was removed, "99" remains
    assert book.bid_levels == 1


def test_delete_action_with_nonzero_size_is_rejected() -> None:
    session = DeribitReplaySession()
    with pytest.raises(Exception, match="zero size"):
        session.apply(
            _book("snapshot", 1, bids=[["delete", "100", "1"]], asks=[["new", "101", "1"]])
        )


def test_crossed_book_is_rejected() -> None:
    session = DeribitReplaySession()
    with pytest.raises(InvalidOrderBook):
        session.apply(
            _book("snapshot", 1, bids=[["new", "100", "1"]], asks=[["new", "99", "1"]])
        )


def test_connection_change_requires_a_fresh_snapshot() -> None:
    session = DeribitReplaySession()
    session.apply(
        _book(
            "snapshot",
            100,
            bids=[["new", "100", "1"]],
            asks=[["new", "101", "1"]],
            connection="conn-1",
        )
    )
    session.apply(_book("change", 101, 100, bids=[["new", "100", "2"]], connection="conn-1"))

    with pytest.raises(DeribitSnapshotRequired):
        session.apply(_book("change", 102, 101, connection="conn-2"))


def test_other_symbols_are_unaffected_by_one_symbols_gap() -> None:
    session = DeribitReplaySession()
    session.apply(
        _book(
            "snapshot",
            100,
            bids=[["new", "100", "1"]],
            asks=[["new", "101", "1"]],
            instrument="BTC-PERPETUAL",
        )
    )
    session.apply(
        _book(
            "snapshot",
            40,
            bids=[["new", "40", "1"]],
            asks=[["new", "41", "1"]],
            instrument="ETH-PERPETUAL",
        )
    )
    session.apply(_book("change", 101, 100, bids=[["new", "100", "2"]], instrument="BTC-PERPETUAL"))
    session.apply(
        _book("change", 41, 40, bids=[["new", "40.5", "1"]], instrument="ETH-PERPETUAL")
    )

    with pytest.raises(DeribitSequenceGap):
        session.apply(_book("change", 103, 102, instrument="BTC-PERPETUAL"))  # BTC gap only

    report = session.report()
    assert report.orderbooks["ETH-PERPETUAL"].change_id == 41  # untouched by BTC's gap


def test_non_orderbook_channels_are_counted_but_do_not_affect_book_state() -> None:
    trade_payload = {
        "jsonrpc": "2.0",
        "method": "subscription",
        "params": {
            "channel": "trades.BTC-PERPETUAL.100ms",
            "data": [
                {
                    "instrument_name": "BTC-PERPETUAL",
                    "trade_id": "1",
                    "price": 100,
                    "amount": 1,
                    "direction": "sell",
                    "timestamp": 1_700_000_000_000,
                }
            ],
        },
    }
    trade_event = parse_deribit_message(
        json.dumps(trade_payload), receive_ts_ns=1, connection_id="conn-1"
    )

    session = DeribitReplaySession()
    session.apply(
        _book("snapshot", 10, bids=[["new", "100", "1"]], asks=[["new", "101", "1"]])
    )
    session.apply(trade_event)

    report = session.report()
    assert report.channel_counts["trades"] == 1
    assert report.orderbooks["BTC-PERPETUAL"].change_id == 10


def test_replay_is_deterministic() -> None:
    def events():
        return [
            _book("snapshot", 10, bids=[["new", "100", "1"]], asks=[["new", "101", "1"]]),
            _book("change", 11, 10, bids=[["new", "100", "2"]]),
        ]

    a = replay_deribit(events())
    b = replay_deribit(events())
    assert a.replay_checksum == b.replay_checksum
    assert a.orderbooks["BTC-PERPETUAL"].checksum == b.orderbooks["BTC-PERPETUAL"].checksum


def test_replay_deribit_sorts_by_receive_order_not_insertion_order() -> None:
    early_snapshot = _book(
        "snapshot", 10, bids=[["new", "100", "1"]], asks=[["new", "101", "1"]], receive_ts_ns=1
    )
    late_delta = _book("change", 11, 10, bids=[["new", "100", "2"]], receive_ts_ns=2)

    report = replay_deribit([late_delta, early_snapshot])  # out of order input

    assert report.orderbooks["BTC-PERPETUAL"].change_id == 11
