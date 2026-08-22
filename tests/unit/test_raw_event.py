"""Raw event envelopes retain exact transport payloads and venue metadata."""

from __future__ import annotations

import hashlib

import pytest

from src.data.raw_event import RawEventError, RawMarketEvent, parse_bybit_message


def test_bybit_orderbook_envelope_preserves_exact_payload() -> None:
    payload = (
        '{"topic":"orderbook.50.BTCUSDT", "type":"delta", "ts":1700000000000,'
        '"data":{"s":"BTCUSDT","b":[["100","1"]],"a":[],"u":12,"seq":99},'
        '"cts":1699999999999}'
    )

    event = parse_bybit_message(
        payload, receive_ts_ns=1_700_000_000_001_000_000, connection_id="conn-1"
    )

    assert event.payload_text == payload
    assert event.payload_sha256 == hashlib.sha256(payload.encode("utf-8")).hexdigest()
    assert event.channel == "orderbook"
    assert event.symbol == "BTCUSDT"
    assert event.message_type == "delta"
    assert event.receive_sequence == 1
    assert event.update_id == 12
    assert event.sequence == 99
    assert event.matching_ts_ms == 1_699_999_999_999


def test_bybit_trade_uses_entry_sequence_and_taker_symbol() -> None:
    payload = (
        '{"topic":"publicTrade.ETHUSDT","type":"snapshot","ts":10,'
        '"data":[{"T":9,"s":"ETHUSDT","S":"Buy","v":"1","p":"2",'
        '"i":"trade-1","seq":7}]}'
    )

    event = parse_bybit_message(payload, receive_ts_ns=11_000_000, connection_id="c")

    assert event.channel == "trades"
    assert event.symbol == "ETHUSDT"
    assert event.sequence == 7
    assert event.update_id is None


def test_control_messages_are_retained_in_a_control_partition() -> None:
    payload = '{"success":true,"ret_msg":"subscribe","op":"subscribe"}'

    event = parse_bybit_message(payload, receive_ts_ns=10, connection_id="c")

    assert event.channel == "control"
    assert event.symbol == "ALL"
    assert event.message_type == "subscribe"


def test_invalid_json_is_rejected() -> None:
    with pytest.raises(RawEventError, match="not valid JSON"):
        parse_bybit_message("not-json", receive_ts_ns=10, connection_id="c")


def test_record_round_trip_revalidates_payload_hash() -> None:
    event = parse_bybit_message("{}", receive_ts_ns=10, connection_id="c")
    record = event.to_record()
    assert RawMarketEvent.from_record(record) == event

    record["payload_text"] = '{"changed":true}'
    with pytest.raises(RawEventError, match="does not match"):
        RawMarketEvent.from_record(record)
