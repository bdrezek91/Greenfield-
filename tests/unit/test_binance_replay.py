"""Binance snapshot/delta replay must never guess through sequence
uncertainty - the Binance counterpart to test_bybit_replay.py, adapted to
Binance's REST-snapshot-bridge + U/u/pu protocol (see
src/data/binance_replay.py's module docstring for the differences).
"""

from __future__ import annotations

import json

import pytest

from src.data.binance_adapter import (
    BinanceSequenceGap,
    BinanceSnapshotRequired,
    parse_binance_message,
    synthesize_binance_depth_snapshot_event,
)
from src.data.binance_replay import (
    BinanceOrderBook,
    BinanceReplaySession,
    InvalidOrderBook,
    replay_binance,
)


def _snapshot_event(
    update_id: int,
    *,
    bids: list[list[str]] | None = None,
    asks: list[list[str]] | None = None,
    receive_ts_ns: int = 1_700_000_000_000_000_000,
    connection_id: str = "conn-1",
    symbol: str = "BTCUSDT",
):
    return synthesize_binance_depth_snapshot_event(
        symbol,
        {
            "lastUpdateId": update_id,
            "E": 1_700_000_000_000,
            "T": 1_700_000_000_000,
            "bids": bids if bids is not None else [],
            "asks": asks if asks is not None else [],
        },
        receive_ts_ns=receive_ts_ns,
        connection_id=connection_id,
    )


def _delta_event(
    first_update_id: int,
    final_update_id: int,
    previous_final_update_id: int,
    *,
    bids: list[list[str]] | None = None,
    asks: list[list[str]] | None = None,
    receive_ts_ns: int | None = None,
    connection_id: str = "conn-1",
    symbol: str = "BTCUSDT",
):
    payload = json.dumps(
        {
            "stream": f"{symbol.lower()}@depth@100ms",
            "data": {
                "e": "depthUpdate",
                "E": 1_700_000_000_000,
                "T": 1_700_000_000_000,
                "s": symbol,
                "U": first_update_id,
                "u": final_update_id,
                "pu": previous_final_update_id,
                "b": bids if bids is not None else [],
                "a": asks if asks is not None else [],
            },
        },
        separators=(",", ":"),
    )
    return parse_binance_message(
        payload,
        receive_ts_ns=receive_ts_ns or 1_700_000_000_000_000_000 + final_update_id,
        connection_id=connection_id,
    )


def test_snapshot_then_delta_rebuilds_exact_decimal_book() -> None:
    session = BinanceReplaySession()
    session.apply(
        _snapshot_event(10, bids=[["100.10", "2"], ["100.00", "3"]], asks=[["100.20", "4"]])
    )
    session.apply(
        _delta_event(11, 12, 10, bids=[["100.10", "0"], ["100.05", "7"]], asks=[["100.20", "6"]])
    )

    report = session.report()
    book = report.orderbooks["BTCUSDT"]
    assert book.update_id == 12
    assert book.best_bid == "100.05"
    assert book.best_ask == "100.20"
    assert book.bid_levels == 2


def test_delta_before_snapshot_is_rejected() -> None:
    book = BinanceOrderBook("BTCUSDT")
    with pytest.raises(BinanceSnapshotRequired):
        book.apply_delta([["100", "1"]], [], update_id=1)


def test_replay_raises_snapshot_required_when_no_snapshot_event_exists() -> None:
    """Bronze data collected before Cycle 19 has no snapshot event -
    replay must fail loudly, not silently guess a book state."""
    with pytest.raises(BinanceSnapshotRequired):
        replay_binance([_delta_event(1, 2, 0, bids=[["100", "1"]])])


def test_update_id_gap_after_bootstrap_raises() -> None:
    session = BinanceReplaySession()
    session.apply(_snapshot_event(100, bids=[["100", "1"]], asks=[["101", "1"]]))
    session.apply(_delta_event(50, 150, 100, bids=[["100", "1"]]))  # bridges

    with pytest.raises(BinanceSequenceGap):
        session.apply(_delta_event(300, 400, 250))  # pu mismatch: expected 150


def test_stale_event_at_or_before_snapshot_is_silently_dropped() -> None:
    """Per Binance's documented procedure (BinanceDepthSequenceGate),
    events at or before the snapshot's lastUpdateId are dropped, not
    treated as an error - the book must stay exactly at the snapshot."""
    session = BinanceReplaySession()
    session.apply(_snapshot_event(500, bids=[["100", "1"]], asks=[["101", "1"]]))
    session.apply(_delta_event(300, 400, 250, bids=[["999", "1"]]))  # stale: u=400 <= 500

    report = session.report()
    book = report.orderbooks["BTCUSDT"]
    assert book.update_id == 500
    assert book.best_bid == "100"  # unaffected by the dropped stale delta


def test_crossed_book_is_rejected() -> None:
    session = BinanceReplaySession()
    with pytest.raises(InvalidOrderBook):
        session.apply(_snapshot_event(1, bids=[["100", "1"]], asks=[["99", "1"]]))


def test_connection_change_requires_a_fresh_snapshot() -> None:
    session = BinanceReplaySession()
    session.apply(
        _snapshot_event(100, connection_id="conn-1", bids=[["100", "1"]], asks=[["101", "1"]])
    )
    session.apply(_delta_event(50, 150, 100, bids=[["100", "1"]], connection_id="conn-1"))

    with pytest.raises(BinanceSnapshotRequired):
        session.apply(_delta_event(151, 160, 150, connection_id="conn-2"))


def test_other_symbols_are_unaffected_by_one_symbols_gap() -> None:
    session = BinanceReplaySession()
    session.apply(_snapshot_event(100, symbol="BTCUSDT", bids=[["100", "1"]], asks=[["101", "1"]]))
    session.apply(_snapshot_event(40, symbol="ETHUSDT", bids=[["40", "1"]], asks=[["41", "1"]]))
    session.apply(_delta_event(50, 150, 100, symbol="BTCUSDT", bids=[["100", "1"]]))
    session.apply(_delta_event(20, 50, 40, symbol="ETHUSDT", bids=[["40.5", "1"]]))

    with pytest.raises(BinanceSequenceGap):
        session.apply(_delta_event(300, 400, 250, symbol="BTCUSDT"))  # BTC gap only

    report = session.report()
    assert report.orderbooks["ETHUSDT"].update_id == 50  # untouched by BTC's gap


def test_non_orderbook_channels_are_counted_but_do_not_affect_book_state() -> None:
    trade_payload = json.dumps(
        {
            "stream": "btcusdt@trade",
            "data": {
                "e": "trade",
                "E": 1_700_000_000_000,
                "T": 1_700_000_000_000,
                "s": "BTCUSDT",
                "t": 1,
                "p": "100",
                "q": "1",
                "X": "MARKET",
                "m": True,
            },
        },
        separators=(",", ":"),
    )
    trade_event = parse_binance_message(trade_payload, receive_ts_ns=1, connection_id="conn-1")

    session = BinanceReplaySession()
    session.apply(_snapshot_event(10, bids=[["100", "1"]], asks=[["101", "1"]]))
    session.apply(trade_event)

    report = session.report()
    assert report.channel_counts["trades"] == 1
    assert report.orderbooks["BTCUSDT"].update_id == 10


def test_replay_is_deterministic() -> None:
    def events():
        return [
            _snapshot_event(10, bids=[["100", "1"]], asks=[["101", "1"]]),
            _delta_event(5, 11, 10, bids=[["100", "2"]]),
        ]

    a = replay_binance(events())
    b = replay_binance(events())
    assert a.replay_checksum == b.replay_checksum
    assert a.orderbooks["BTCUSDT"].checksum == b.orderbooks["BTCUSDT"].checksum


def test_replay_binance_sorts_by_receive_order_not_insertion_order() -> None:
    early_snapshot = _snapshot_event(10, receive_ts_ns=1, bids=[["100", "1"]], asks=[["101", "1"]])
    late_delta = _delta_event(5, 11, 10, bids=[["100", "2"]], receive_ts_ns=2)

    report = replay_binance([late_delta, early_snapshot])  # out of order input

    assert report.orderbooks["BTCUSDT"].update_id == 11
