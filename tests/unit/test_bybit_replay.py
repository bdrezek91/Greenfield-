"""Bybit snapshot/delta replay must never guess through sequence uncertainty."""

from __future__ import annotations

import json

import pytest

from src.data.bybit_replay import (
    BybitOrderBook,
    BybitTickerState,
    InvalidOrderBook,
    SequenceGap,
    SequenceRegression,
    SnapshotRequired,
    replay_bybit,
)
from src.data.raw_event import parse_bybit_message


def _book_event(
    message_type: str,
    update_id: int,
    sequence: int,
    *,
    bids: list[list[str]] | None = None,
    asks: list[list[str]] | None = None,
    receive_ts_ns: int | None = None,
    connection_id: str = "conn-1",
):
    payload = json.dumps(
        {
            "topic": "orderbook.50.BTCUSDT",
            "type": message_type,
            "ts": 1_700_000_000_000 + update_id,
            "data": {
                "s": "BTCUSDT",
                "b": bids if bids is not None else [],
                "a": asks if asks is not None else [],
                "u": update_id,
                "seq": sequence,
            },
            "cts": 1_700_000_000_000 + update_id,
        },
        separators=(",", ":"),
    )
    return parse_bybit_message(
        payload,
        receive_ts_ns=receive_ts_ns or 1_700_000_000_000_000_000 + update_id,
        connection_id=connection_id,
    )


def _ticker_event(
    message_type: str,
    sequence: int,
    data: dict[str, str],
    *,
    receive_ts_ns: int,
    connection_id: str = "conn-1",
):
    payload = json.dumps(
        {
            "topic": "tickers.BTCUSDT",
            "type": message_type,
            "cs": sequence,
            "ts": 1_700_000_000_000,
            "data": {"symbol": "BTCUSDT", **data},
        },
        separators=(",", ":"),
    )
    return parse_bybit_message(
        payload, receive_ts_ns=receive_ts_ns, connection_id=connection_id
    )


def test_snapshot_then_delta_rebuilds_exact_decimal_book() -> None:
    book = BybitOrderBook("BTCUSDT")
    book.apply_event(
        _book_event(
            "snapshot",
            10,
            100,
            bids=[["100.10", "2"], ["100.00", "3"]],
            asks=[["100.20", "4"], ["100.30", "5"]],
        )
    )
    book.apply_event(
        _book_event(
            "delta",
            11,
            105,
            bids=[["100.10", "0"], ["100.05", "7"]],
            asks=[["100.20", "6"]],
        )
    )

    snapshot = book.snapshot()
    assert snapshot.update_id == 11
    assert snapshot.best_bid == "100.05"
    assert snapshot.best_ask == "100.20"
    assert snapshot.bid_levels == 2


def test_delta_before_snapshot_is_rejected() -> None:
    with pytest.raises(SnapshotRequired):
        BybitOrderBook("BTCUSDT").apply_event(
            _book_event("delta", 2, 20, bids=[["100", "1"]])
        )


def test_update_id_gap_invalidates_book() -> None:
    book = BybitOrderBook("BTCUSDT")
    book.apply_event(
        _book_event("snapshot", 10, 100, bids=[["100", "1"]], asks=[["101", "1"]])
    )

    with pytest.raises(SequenceGap) as exc_info:
        book.apply_event(_book_event("delta", 12, 110, bids=[["100", "2"]]))

    assert exc_info.value.expected == 11
    assert not book.is_ready


def test_repeated_or_regressed_update_is_rejected() -> None:
    book = BybitOrderBook("BTCUSDT")
    book.apply_event(
        _book_event("snapshot", 10, 100, bids=[["100", "1"]], asks=[["101", "1"]])
    )
    with pytest.raises(SequenceRegression):
        book.apply_event(_book_event("delta", 10, 101, bids=[["100", "2"]]))


def test_crossed_book_is_rejected_without_committing_delta() -> None:
    book = BybitOrderBook("BTCUSDT")
    book.apply_event(
        _book_event("snapshot", 10, 100, bids=[["100", "1"]], asks=[["101", "1"]])
    )
    with pytest.raises(InvalidOrderBook):
        book.apply_event(_book_event("delta", 11, 101, bids=[["102", "1"]]))

    assert book.snapshot().best_bid == "100"


def test_ticker_delta_materializes_unchanged_fields() -> None:
    ticker = BybitTickerState("BTCUSDT")
    ticker.apply_event(
        _ticker_event(
            "snapshot",
            100,
            {"markPrice": "100", "indexPrice": "99", "fundingRate": "0.001"},
            receive_ts_ns=1,
        )
    )
    first_checksum = ticker.checksum()
    ticker.apply_event(
        _ticker_event("delta", 101, {"markPrice": "101"}, receive_ts_ns=2)
    )

    assert ticker.checksum() != first_checksum


def test_ticker_delta_before_snapshot_is_rejected() -> None:
    with pytest.raises(SnapshotRequired):
        BybitTickerState("BTCUSDT").apply_event(
            _ticker_event("delta", 1, {"markPrice": "101"}, receive_ts_ns=1)
        )


def test_replay_is_deterministic_and_connection_boundaries_require_snapshot() -> None:
    snapshot = _book_event(
        "snapshot",
        10,
        100,
        bids=[["100", "1"]],
        asks=[["101", "1"]],
        receive_ts_ns=1,
    )
    delta = _book_event("delta", 11, 101, bids=[["100", "2"]], receive_ts_ns=2)

    first = replay_bybit([delta, snapshot])
    second = replay_bybit([snapshot, delta])
    assert first.replay_checksum == second.replay_checksum
    assert first.orderbooks["BTCUSDT"].update_id == 11

    new_connection_delta = _book_event(
        "delta", 12, 102, bids=[["100", "3"]], receive_ts_ns=3, connection_id="conn-2"
    )
    with pytest.raises(SnapshotRequired):
        replay_bybit([snapshot, delta, new_connection_delta])


def test_receive_sequence_breaks_equal_timestamp_ties() -> None:
    timestamp = 1_700_000_000_000_000_000
    snapshot = _book_event(
        "snapshot",
        10,
        100,
        bids=[["100", "1"]],
        asks=[["101", "1"]],
        receive_ts_ns=timestamp,
    )
    delta_payload = _book_event(
        "delta", 11, 101, bids=[["100", "2"]], receive_ts_ns=timestamp
    ).payload_text
    delta = parse_bybit_message(
        delta_payload,
        receive_ts_ns=timestamp,
        receive_sequence=2,
        connection_id="conn-1",
    )

    assert replay_bybit([delta, snapshot]).orderbooks["BTCUSDT"].update_id == 11
