"""Coinbase snapshot/delta replay must never guess through sequence
uncertainty - the Coinbase counterpart to test_bybit_replay.py/
test_binance_replay.py/test_okx_replay.py, adapted to Coinbase's
CONNECTION-GLOBAL sequence_num (see src/data/coinbase_replay.py's module
docstring for why this is a fundamentally different design from every
other exchange's replay tool in this repo: one gap anywhere on the
connection fails the whole session, not just one product).
"""

from __future__ import annotations

import json

import pytest

from src.data.coinbase_adapter import CoinbaseSequenceGap, parse_coinbase_message
from src.data.coinbase_replay import (
    CoinbaseReplayError,
    CoinbaseReplaySession,
    InvalidOrderBook,
    replay_coinbase,
)


def _level2(
    message_type: str,
    sequence: int | None,
    *,
    bids: list[list[str]] | None = None,
    asks: list[list[str]] | None = None,
    connection: str = "coinbase-c1",
    product_id: str = "BTC-USD",
    receive_ts_ns: int | None = None,
):
    updates = []
    for price, size in bids if bids is not None else []:
        updates.append({"side": "bid", "price_level": price, "new_quantity": size})
    for price, size in asks if asks is not None else []:
        updates.append({"side": "offer", "price_level": price, "new_quantity": size})
    payload: dict = {
        "channel": "l2_data",
        "timestamp": "2023-02-09T20:32:50.714964855Z",
        "events": [{"type": message_type, "product_id": product_id, "updates": updates}],
    }
    if sequence is not None:
        payload["sequence_num"] = sequence
    return parse_coinbase_message(
        json.dumps(payload, separators=(",", ":")),
        receive_ts_ns=receive_ts_ns or 1_700_000_000_000_000_000 + (sequence or 0),
        receive_sequence=(sequence or 0) + 1,
        connection_id=connection,
    )


def _heartbeat(sequence: int, *, connection: str = "coinbase-c1"):
    payload = {"channel": "heartbeats", "sequence_num": sequence, "events": []}
    return parse_coinbase_message(
        json.dumps(payload, separators=(",", ":")),
        receive_ts_ns=1_700_000_000_000_000_000 + sequence,
        receive_sequence=sequence + 1,
        connection_id=connection,
    )


def test_snapshot_then_delta_rebuilds_exact_decimal_book() -> None:
    session = CoinbaseReplaySession()
    session.apply(
        _level2(
            "snapshot",
            0,
            bids=[["100.10", "2"], ["100.00", "3"]],
            asks=[["100.20", "4"]],
        )
    )
    session.apply(
        _level2(
            "update",
            1,
            bids=[["100.10", "0"], ["100.05", "7"]],
            asks=[["100.20", "6"]],
        )
    )

    report = session.report()
    book = report.orderbooks["BTC-USD"]
    assert book.last_sequence_num == 1
    assert book.best_bid == "100.05"
    assert book.best_ask == "100.20"
    assert book.bid_levels == 2


def test_delta_before_snapshot_is_rejected() -> None:
    session = CoinbaseReplaySession()
    with pytest.raises(CoinbaseReplayError, match="before a valid snapshot"):
        session.apply(_level2("update", 0, bids=[["100", "1"]]))


def test_a_gap_on_an_unrelated_channel_fails_the_whole_session() -> None:
    """The defining Coinbase difference: sequence_num is connection-global,
    so a gap on a non-orderbook message (e.g. a dropped heartbeat) means
    the WHOLE connection's data from that point is suspect - not just one
    product's book. This is exactly why CoinbaseConnectionSequenceGate,
    not a per-product gate, is used here."""
    session = CoinbaseReplaySession()
    session.apply(
        _level2("snapshot", 0, bids=[["100", "1"]], asks=[["101", "1"]])
    )

    with pytest.raises(CoinbaseSequenceGap):
        session.apply(_heartbeat(5))  # expected sequence_num=1, observed 5


def test_messages_without_sequence_num_do_not_break_continuity() -> None:
    session = CoinbaseReplaySession()
    payload = {"channel": "subscriptions", "events": []}  # no sequence_num field
    no_seq_event = parse_coinbase_message(
        json.dumps(payload), receive_ts_ns=1, connection_id="coinbase-c1"
    )

    session.apply(no_seq_event)
    session.apply(_level2("snapshot", 0, bids=[["100", "1"]], asks=[["101", "1"]]))
    session.apply(_level2("update", 1, bids=[["100", "2"]]))

    report = session.report()
    assert report.orderbooks["BTC-USD"].last_sequence_num == 1


def test_crossed_book_is_rejected() -> None:
    session = CoinbaseReplaySession()
    with pytest.raises(InvalidOrderBook):
        session.apply(_level2("snapshot", 0, bids=[["100", "1"]], asks=[["99", "1"]]))


def test_reconnect_resets_the_gate_without_raising() -> None:
    session = CoinbaseReplaySession()
    session.apply(
        _level2("snapshot", 0, bids=[["100", "1"]], asks=[["101", "1"]], connection="conn-1")
    )
    session.apply(_level2("update", 1, bids=[["100", "2"]], connection="conn-1"))

    # A reconnect (new connection_id) starts a brand-new counter series -
    # not a rollback of the old one - so a lower sequence_num is fine.
    session.apply(
        _level2("snapshot", 0, bids=[["50", "1"]], asks=[["51", "1"]], connection="conn-2")
    )

    report = session.report()
    assert report.orderbooks["BTC-USD"].best_bid == "50"


def test_multiple_products_share_one_connection_gate() -> None:
    session = CoinbaseReplaySession()
    session.apply(
        _level2(
            "snapshot", 0, bids=[["100", "1"]], asks=[["101", "1"]], product_id="BTC-USD"
        )
    )
    session.apply(_level2("update", 1, bids=[["100", "2"]], product_id="BTC-USD"))
    session.apply(
        _level2(
            "snapshot", 2, bids=[["50", "1"]], asks=[["51", "1"]], product_id="ETH-USD"
        )
    )

    with pytest.raises(CoinbaseSequenceGap):
        # ETH-USD's own gap breaks the SHARED connection counter, not just
        # ETH-USD's book - demonstrating this is not per-product isolation.
        session.apply(_level2("update", 10, product_id="ETH-USD"))


def test_multi_product_single_message_is_rejected() -> None:
    payload = {
        "channel": "l2_data",
        "sequence_num": 0,
        "events": [
            {"type": "snapshot", "product_id": "BTC-USD", "updates": []},
            {"type": "snapshot", "product_id": "ETH-USD", "updates": []},
        ],
    }
    event = parse_coinbase_message(
        json.dumps(payload), receive_ts_ns=1, connection_id="coinbase-c1"
    )
    assert event.symbol == "MULTI"

    session = CoinbaseReplaySession()
    with pytest.raises(CoinbaseReplayError, match="exactly one product"):
        session.apply(event)


def test_replay_is_deterministic() -> None:
    def events():
        return [
            _level2("snapshot", 0, bids=[["100", "1"]], asks=[["101", "1"]]),
            _level2("update", 1, bids=[["100", "2"]]),
        ]

    a = replay_coinbase(events())
    b = replay_coinbase(events())
    assert a.replay_checksum == b.replay_checksum
    assert a.orderbooks["BTC-USD"].checksum == b.orderbooks["BTC-USD"].checksum


def test_replay_coinbase_sorts_by_receive_order_not_insertion_order() -> None:
    early_snapshot = _level2(
        "snapshot", 0, bids=[["100", "1"]], asks=[["101", "1"]], receive_ts_ns=1
    )
    late_delta = _level2("update", 1, bids=[["100", "2"]], receive_ts_ns=2)

    report = replay_coinbase([late_delta, early_snapshot])  # out of order input

    assert report.orderbooks["BTC-USD"].last_sequence_num == 1
