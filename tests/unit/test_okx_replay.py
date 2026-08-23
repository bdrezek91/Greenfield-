"""OKX snapshot/delta replay must never guess through sequence uncertainty
- the OKX counterpart to test_bybit_replay.py/test_binance_replay.py,
adapted to OKX's self-bootstrapping seqId/prevSeqId protocol (see
src/data/okx_replay.py's module docstring for the differences).
"""

from __future__ import annotations

import json

import pytest

from src.data.okx_adapter import OkxSequenceGap, OkxSnapshotRequired, parse_okx_message
from src.data.okx_replay import InvalidOrderBook, OkxReplaySession, replay_okx


def _book(
    action: str,
    sequence: int,
    previous: int,
    *,
    connection: str = "okx-c1",
    bids: list[list[str]] | None = None,
    asks: list[list[str]] | None = None,
    inst_id: str = "BTC-USDT-SWAP",
    receive_ts_ns: int | None = None,
):
    payload = {
        "arg": {"channel": "books", "instId": inst_id},
        "action": action,
        "data": [
            {
                "asks": [] if asks is None else asks,
                "bids": [] if bids is None else bids,
                "ts": "1700000000000",
                "seqId": sequence,
                "prevSeqId": previous,
                "checksum": 0,
            }
        ],
    }
    return parse_okx_message(
        json.dumps(payload, separators=(",", ":")),
        receive_ts_ns=receive_ts_ns or 1_700_000_000_001_000_000 + sequence,
        connection_id=connection,
        receive_sequence=max(sequence, 1),
    )


def test_snapshot_then_delta_rebuilds_exact_decimal_book() -> None:
    session = OkxReplaySession()
    session.apply(
        _book(
            "snapshot",
            100,
            -1,
            bids=[["100.10", "2", "0", "1"], ["100.00", "3", "0", "1"]],
            asks=[["100.20", "4", "0", "1"]],
        )
    )
    session.apply(
        _book(
            "update",
            101,
            100,
            bids=[["100.10", "0", "0", "0"], ["100.05", "7", "0", "1"]],
            asks=[["100.20", "6", "0", "1"]],
        )
    )

    report = session.report()
    book = report.orderbooks["BTC-USDT-SWAP"]
    assert book.sequence == 101
    assert book.best_bid == "100.05"
    assert book.best_ask == "100.20"
    assert book.bid_levels == 2


def test_delta_before_snapshot_is_rejected() -> None:
    session = OkxReplaySession()
    with pytest.raises(OkxSnapshotRequired):
        session.apply(_book("update", 101, 100, bids=[["100", "1", "0", "1"]]))


def test_gap_after_bootstrap_raises() -> None:
    session = OkxReplaySession()
    session.apply(
        _book("snapshot", 100, -1, bids=[["100", "1", "0", "1"]], asks=[["101", "1", "0", "1"]])
    )
    session.apply(_book("update", 101, 100, bids=[["100", "2", "0", "1"]]))

    with pytest.raises(OkxSequenceGap):
        session.apply(_book("update", 103, 102))  # expected prevSeqId=101


def test_heartbeat_does_not_change_book_state() -> None:
    session = OkxReplaySession()
    session.apply(
        _book("snapshot", 100, -1, bids=[["100", "1", "0", "1"]], asks=[["101", "1", "0", "1"]])
    )
    session.apply(_book("update", 100, 100, bids=[], asks=[]))  # heartbeat: seq unchanged

    report = session.report()
    book = report.orderbooks["BTC-USDT-SWAP"]
    assert book.sequence == 100
    assert book.best_bid == "100"


def test_crossed_book_is_rejected() -> None:
    session = OkxReplaySession()
    with pytest.raises(InvalidOrderBook):
        session.apply(
            _book("snapshot", 1, -1, bids=[["100", "1", "0", "1"]], asks=[["99", "1", "0", "1"]])
        )


def test_connection_change_requires_a_fresh_snapshot() -> None:
    session = OkxReplaySession()
    session.apply(
        _book(
            "snapshot",
            100,
            -1,
            bids=[["100", "1", "0", "1"]],
            asks=[["101", "1", "0", "1"]],
            connection="conn-1",
        )
    )
    session.apply(_book("update", 101, 100, bids=[["100", "2", "0", "1"]], connection="conn-1"))

    with pytest.raises(OkxSnapshotRequired):
        session.apply(_book("update", 102, 101, connection="conn-2"))


def test_other_symbols_are_unaffected_by_one_symbols_gap() -> None:
    session = OkxReplaySession()
    session.apply(
        _book(
            "snapshot",
            100,
            -1,
            bids=[["100", "1", "0", "1"]],
            asks=[["101", "1", "0", "1"]],
            inst_id="BTC-USDT-SWAP",
        )
    )
    session.apply(
        _book(
            "snapshot",
            40,
            -1,
            bids=[["40", "1", "0", "1"]],
            asks=[["41", "1", "0", "1"]],
            inst_id="ETH-USDT-SWAP",
        )
    )
    session.apply(_book("update", 101, 100, bids=[["100", "2", "0", "1"]], inst_id="BTC-USDT-SWAP"))
    session.apply(_book("update", 41, 40, bids=[["40.5", "1", "0", "1"]], inst_id="ETH-USDT-SWAP"))

    with pytest.raises(OkxSequenceGap):
        session.apply(_book("update", 103, 102, inst_id="BTC-USDT-SWAP"))  # BTC gap only

    report = session.report()
    assert report.orderbooks["ETH-USDT-SWAP"].sequence == 41  # untouched by BTC's gap


def test_non_orderbook_channels_are_counted_but_do_not_affect_book_state() -> None:
    trade_payload = {
        "arg": {"channel": "trades", "instId": "BTC-USDT-SWAP"},
        "data": [
            {
                "instId": "BTC-USDT-SWAP",
                "tradeId": "1",
                "px": "100",
                "sz": "1",
                "side": "sell",
                "ts": "1700000000000",
            }
        ],
    }
    trade_event = parse_okx_message(
        json.dumps(trade_payload), receive_ts_ns=1, connection_id="conn-1"
    )

    session = OkxReplaySession()
    session.apply(
        _book("snapshot", 10, -1, bids=[["100", "1", "0", "1"]], asks=[["101", "1", "0", "1"]])
    )
    session.apply(trade_event)

    report = session.report()
    assert report.channel_counts["trades"] == 1
    assert report.orderbooks["BTC-USDT-SWAP"].sequence == 10


def test_replay_is_deterministic() -> None:
    def events():
        return [
            _book("snapshot", 10, -1, bids=[["100", "1", "0", "1"]], asks=[["101", "1", "0", "1"]]),
            _book("update", 11, 10, bids=[["100", "2", "0", "1"]]),
        ]

    a = replay_okx(events())
    b = replay_okx(events())
    assert a.replay_checksum == b.replay_checksum
    assert a.orderbooks["BTC-USDT-SWAP"].checksum == b.orderbooks["BTC-USDT-SWAP"].checksum


def test_replay_okx_sorts_by_receive_order_not_insertion_order() -> None:
    early_snapshot = _book(
        "snapshot",
        10,
        -1,
        bids=[["100", "1", "0", "1"]],
        asks=[["101", "1", "0", "1"]],
        receive_ts_ns=1,
    )
    late_delta = _book("update", 11, 10, bids=[["100", "2", "0", "1"]], receive_ts_ns=2)

    report = replay_okx([late_delta, early_snapshot])  # out of order input

    assert report.orderbooks["BTC-USDT-SWAP"].sequence == 11
