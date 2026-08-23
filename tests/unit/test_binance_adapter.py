from __future__ import annotations

import hashlib

import pytest

from src.data.binance_adapter import (
    BinanceDepthSequenceGate,
    BinanceSequenceGap,
    BinanceSnapshotRequired,
    parse_binance_message,
    synthesize_binance_depth_snapshot_event,
)
from src.data.raw_event import RawEventError


def _depth(
    first: int,
    final: int,
    previous: int,
    *,
    connection: str = "c1",
):
    payload = (
        '{"stream":"btcusdt@depth@100ms","data":{"e":"depthUpdate",'
        f'"E":1700000000000,"T":1699999999999,"s":"BTCUSDT","U":{first},'
        f'"u":{final},"pu":{previous},"b":[["100","1"]],"a":[]}}}}'
    )
    return parse_binance_message(
        payload,
        receive_ts_ns=1_700_000_000_001_000_000 + final,
        connection_id=connection,
        receive_sequence=final,
    )


def test_binance_combined_depth_envelope_preserves_payload_and_metadata() -> None:
    event = _depth(101, 102, 100)

    assert event.exchange == "binance"
    assert event.channel == "orderbook"
    assert event.topic == "btcusdt@depth@100ms"
    assert event.symbol == "BTCUSDT"
    assert event.sequence == 101
    assert event.update_id == 102
    assert event.matching_ts_ms == 1_699_999_999_999
    assert event.payload_sha256 == hashlib.sha256(
        event.payload_text.encode("utf-8")
    ).hexdigest()


def test_binance_aggregate_trade_retains_taker_side_source_fields() -> None:
    payload = (
        '{"e":"aggTrade","E":1700000000001,"s":"ETHUSDT","a":5933014,'
        '"p":"100.10","q":"0.25","f":100,"l":105,'
        '"T":1700000000000,"m":true}'
    )
    event = parse_binance_message(payload, receive_ts_ns=2, connection_id="c")

    assert event.channel == "trades"
    assert event.symbol == "ETHUSDT"
    assert event.sequence == 5_933_014
    assert event.matching_ts_ms == 1_700_000_000_000
    assert event.payload()["m"] is True


def test_binance_depth_gate_bridges_snapshot_then_enforces_previous_update() -> None:
    gate = BinanceDepthSequenceGate("BTCUSDT")
    gate.bootstrap(snapshot_update_id=100, connection_id="c1")

    assert gate.apply(_depth(99, 102, 98)) is True
    assert gate.apply(_depth(103, 104, 102)) is True
    assert gate.update_id == 104
    assert gate.apply(_depth(103, 104, 102)) is False


def test_binance_depth_gap_or_connection_change_requires_fresh_snapshot() -> None:
    gate = BinanceDepthSequenceGate("BTCUSDT")
    gate.bootstrap(snapshot_update_id=100, connection_id="c1")
    with pytest.raises(BinanceSequenceGap, match="bridge"):
        gate.apply(_depth(102, 103, 101))
    with pytest.raises(BinanceSnapshotRequired):
        gate.apply(_depth(101, 102, 100))

    gate.bootstrap(snapshot_update_id=100, connection_id="c1")
    with pytest.raises(BinanceSnapshotRequired, match="connection changed"):
        gate.apply(_depth(101, 102, 100, connection="c2"))


def test_binance_parser_rejects_lossy_or_invalid_shapes() -> None:
    with pytest.raises(RawEventError, match="not valid JSON"):
        parse_binance_message("bad", receive_ts_ns=1, connection_id="c")
    with pytest.raises(RawEventError, match="JSON object"):
        parse_binance_message("[]", receive_ts_ns=1, connection_id="c")


def test_binance_force_order_is_the_liquidations_channel_with_nested_symbol() -> None:
    payload = (
        '{"stream":"btcusdt@forceOrder","data":{"e":"forceOrder","E":1700000000000,'
        '"o":{"s":"BTCUSDT","S":"SELL","o":"LIMIT","f":"IOC","q":"0.014",'
        '"p":"77000.00","ap":"77000.00","X":"FILLED","l":"0.014","z":"0.014",'
        '"T":1700000000000}}}'
    )
    event = parse_binance_message(payload, receive_ts_ns=1, connection_id="c")

    assert event.channel == "liquidations"
    assert event.symbol == "BTCUSDT"
    assert event.payload()["data"]["o"]["S"] == "SELL"


def _rest_snapshot(last_update_id: int = 500) -> dict:
    return {
        "lastUpdateId": last_update_id,
        "E": 1_700_000_000_000,
        "T": 1_700_000_000_000,
        "bids": [["100.00", "1.5"], ["99.90", "2.0"]],
        "asks": [["100.10", "0.5"]],
    }


def test_synthesize_binance_depth_snapshot_event_preserves_real_price_levels() -> None:
    event = synthesize_binance_depth_snapshot_event(
        "BTCUSDT",
        _rest_snapshot(),
        receive_ts_ns=1,
        connection_id="c1",
    )

    assert event.exchange == "binance"
    assert event.channel == "orderbook"
    assert event.message_type == "snapshot"
    assert event.symbol == "BTCUSDT"
    assert event.update_id == 500
    payload = event.payload()
    assert payload["bids"] == [["100.00", "1.5"], ["99.90", "2.0"]]
    assert payload["asks"] == [["100.10", "0.5"]]


def test_synthesize_binance_depth_snapshot_event_is_not_wrapped_in_a_stream_envelope() -> None:
    """Unlike a real WS message, this has no {"stream":..,"data":{...}}
    wrapper - a consumer must special-case message_type == "snapshot"."""
    event = synthesize_binance_depth_snapshot_event(
        "BTCUSDT", _rest_snapshot(), receive_ts_ns=1, connection_id="c1"
    )
    payload = event.payload()
    assert "data" not in payload
    assert "stream" not in payload
    assert payload["lastUpdateId"] == 500


def test_synthesize_binance_depth_snapshot_event_rejects_missing_last_update_id() -> None:
    with pytest.raises(Exception, match="lastUpdateId"):
        synthesize_binance_depth_snapshot_event(
            "BTCUSDT", {"bids": [], "asks": []}, receive_ts_ns=1, connection_id="c1"
        )


def test_synthesize_binance_depth_snapshot_event_is_deterministic_for_identical_input() -> None:
    a = synthesize_binance_depth_snapshot_event(
        "BTCUSDT", _rest_snapshot(), receive_ts_ns=1, connection_id="c1", receive_sequence=1
    )
    b = synthesize_binance_depth_snapshot_event(
        "BTCUSDT", _rest_snapshot(), receive_ts_ns=1, connection_id="c1", receive_sequence=1
    )
    assert a.event_id == b.event_id
    assert a.payload_sha256 == b.payload_sha256
