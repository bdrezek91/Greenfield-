from __future__ import annotations

import hashlib
import json

import pytest

from src.data.okx_adapter import (
    OkxSequenceGap,
    OkxSequenceGate,
    OkxSnapshotRequired,
    parse_okx_message,
)
from src.data.raw_event import RawEventError


def _book(
    action: str,
    sequence: int,
    previous: int,
    *,
    connection: str = "okx-c1",
    bids: list[list[str]] | None = None,
    asks: list[list[str]] | None = None,
):
    payload = {
        "arg": {"channel": "books", "instId": "BTC-USDT-SWAP"},
        "action": action,
        "data": [
            {
                "asks": [] if asks is None else asks,
                "bids": [["100", "1", "0", "1"]] if bids is None else bids,
                "ts": "1700000000000",
                "seqId": sequence,
                "prevSeqId": previous,
                "checksum": 0,
            }
        ],
    }
    return parse_okx_message(
        json.dumps(payload, separators=(",", ":")),
        receive_ts_ns=1_700_000_000_001_000_000 + sequence,
        connection_id=connection,
        receive_sequence=max(sequence, 1),
    )


def test_okx_book_envelope_preserves_exact_payload_and_sequence_metadata() -> None:
    event = _book("snapshot", 101, -1)

    assert event.exchange == "okx"
    assert event.market_type == "swap"
    assert event.channel == "orderbook"
    assert event.topic == "books"
    assert event.symbol == "BTC-USDT-SWAP"
    assert event.message_type == "snapshot"
    assert event.exchange_ts_ms == 1_700_000_000_000
    assert event.sequence == 101
    assert event.update_id == 101
    assert event.payload_sha256 == hashlib.sha256(event.payload_text.encode("utf-8")).hexdigest()
    assert event.payload()["data"][0]["checksum"] == 0


def test_okx_public_trade_keeps_taker_side_and_exact_venue_fields() -> None:
    payload = {
        "arg": {"channel": "trades", "instId": "ETH-USDT-SWAP"},
        "data": [
            {
                "instId": "ETH-USDT-SWAP",
                "tradeId": "12345",
                "px": "2000.50",
                "sz": "3",
                "side": "sell",
                "ts": "1700000000001",
                "source": "0",
            }
        ],
    }
    event = parse_okx_message(json.dumps(payload), receive_ts_ns=2, connection_id="okx-c")

    assert event.channel == "trades"
    assert event.symbol == "ETH-USDT-SWAP"
    assert event.exchange_ts_ms == 1_700_000_000_001
    assert event.payload()["data"][0]["side"] == "sell"
    assert event.payload()["data"][0]["source"] == "0"


def test_okx_sequence_gate_accepts_snapshot_updates_and_heartbeat() -> None:
    gate = OkxSequenceGate("BTC-USDT-SWAP")

    assert gate.apply(_book("snapshot", 100, -1)) is True
    assert gate.apply(_book("update", 101, 100)) is True
    assert gate.apply(_book("update", 101, 101, bids=[], asks=[])) is False
    assert gate.sequence == 101


def test_okx_gap_or_connection_change_requires_fresh_snapshot() -> None:
    gate = OkxSequenceGate("BTC-USDT-SWAP")

    with pytest.raises(OkxSnapshotRequired, match="fresh snapshot"):
        gate.apply(_book("update", 101, 100))

    gate.apply(_book("snapshot", 100, -1))
    with pytest.raises(OkxSequenceGap, match="prevSeqId=100"):
        gate.apply(_book("update", 102, 99))
    with pytest.raises(OkxSnapshotRequired, match="fresh snapshot"):
        gate.apply(_book("update", 103, 102))

    gate.apply(_book("snapshot", 200, -1))
    with pytest.raises(OkxSnapshotRequired, match="connection changed"):
        gate.apply(_book("update", 201, 200, connection="okx-c2"))


def test_okx_parser_rejects_invalid_or_lossy_shapes() -> None:
    with pytest.raises(RawEventError, match="not valid JSON"):
        parse_okx_message("bad", receive_ts_ns=1, connection_id="c")
    with pytest.raises(RawEventError, match="JSON object"):
        parse_okx_message("[]", receive_ts_ns=1, connection_id="c")
    with pytest.raises(RawEventError, match="arg must be an object"):
        parse_okx_message('{"arg":[]}', receive_ts_ns=1, connection_id="c")


def test_okx_subscription_ack_is_control_even_with_market_channel_argument() -> None:
    event = parse_okx_message(
        '{"event":"subscribe","arg":{"channel":"tickers","instId":"BTC-USDT-SWAP"}}',
        receive_ts_ns=1,
        connection_id="c",
    )

    assert event.channel == "control"
    assert event.topic == "tickers"
    assert event.message_type == "subscribe"
