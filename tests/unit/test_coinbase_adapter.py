from __future__ import annotations

import hashlib
import json

import pytest

from src.data.coinbase_adapter import (
    CoinbaseLevel2SequenceGate,
    CoinbaseSequenceGap,
    CoinbaseSnapshotRequired,
    parse_coinbase_message,
)
from src.data.raw_event import RawEventError


def _level2(
    message_type: str,
    sequence: int,
    *,
    connection: str = "coinbase-c1",
):
    payload = {
        "channel": "l2_data",
        "timestamp": "2023-02-09T20:32:50.714964855Z",
        "sequence_num": sequence,
        "events": [
            {
                "type": message_type,
                "product_id": "BTC-USD",
                "updates": [
                    {
                        "side": "bid",
                        "event_time": "2023-02-09T20:32:50.700Z",
                        "price_level": "21921.73",
                        "new_quantity": "0.06317902",
                    }
                ],
            }
        ],
    }
    return parse_coinbase_message(
        json.dumps(payload, separators=(",", ":")),
        receive_ts_ns=1_700_000_000_000_000_000 + sequence,
        receive_sequence=sequence + 1,
        connection_id=connection,
    )


def test_coinbase_l2_envelope_preserves_payload_and_metadata() -> None:
    event = _level2("snapshot", 0)

    assert event.exchange == "coinbase"
    assert event.market_type == "spot"
    assert event.channel == "orderbook"
    assert event.topic == "l2_data"
    assert event.symbol == "BTC-USD"
    assert event.message_type == "snapshot"
    assert event.sequence == 0
    assert event.update_id == 0
    assert event.payload_sha256 == hashlib.sha256(event.payload_text.encode("utf-8")).hexdigest()


def test_coinbase_multi_product_message_is_preserved_but_marked_ambiguous() -> None:
    payload = {
        "channel": "market_trades",
        "timestamp": "2023-02-09T20:19:35Z",
        "sequence_num": 1,
        "events": [
            {
                "type": "update",
                "trades": [
                    {"product_id": "BTC-USD"},
                    {"product_id": "ETH-USD"},
                ],
            }
        ],
    }
    event = parse_coinbase_message(json.dumps(payload), receive_ts_ns=1, connection_id="c")

    assert event.symbol == "MULTI"
    assert event.payload()["events"][0]["trades"][1]["product_id"] == "ETH-USD"


def test_coinbase_level2_gate_enforces_snapshot_connection_and_sequence() -> None:
    gate = CoinbaseLevel2SequenceGate("BTC-USD")

    with pytest.raises(CoinbaseSnapshotRequired, match="fresh snapshot"):
        gate.apply(_level2("update", 1))
    assert gate.apply(_level2("snapshot", 10)) is True
    assert gate.apply(_level2("update", 11)) is True
    assert gate.apply(_level2("update", 11)) is False
    with pytest.raises(CoinbaseSequenceGap, match="expected sequence_num=12"):
        gate.apply(_level2("update", 13))

    gate.apply(_level2("snapshot", 20))
    with pytest.raises(CoinbaseSnapshotRequired, match="connection changed"):
        gate.apply(_level2("update", 21, connection="coinbase-c2"))


def test_coinbase_parser_rejects_invalid_shapes_and_timestamps() -> None:
    with pytest.raises(RawEventError, match="not valid JSON"):
        parse_coinbase_message("bad", receive_ts_ns=1, connection_id="c")
    with pytest.raises(RawEventError, match="JSON object"):
        parse_coinbase_message("[]", receive_ts_ns=1, connection_id="c")
    with pytest.raises(RawEventError, match="events must be"):
        parse_coinbase_message('{"events":{}}', receive_ts_ns=1, connection_id="c")
    with pytest.raises(RawEventError, match="timezone-aware"):
        parse_coinbase_message(
            '{"timestamp":"2023-01-01T00:00:00","events":[]}',
            receive_ts_ns=1,
            connection_id="c",
        )
