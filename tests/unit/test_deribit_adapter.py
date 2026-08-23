from __future__ import annotations

import hashlib
import json

import pytest

from src.data.deribit_adapter import (
    DeribitBookSequenceGate,
    DeribitSequenceGap,
    DeribitSnapshotRequired,
    parse_deribit_message,
)
from src.data.raw_event import RawEventError


def _book(
    message_type: str,
    change_id: int,
    previous: int | None = None,
    *,
    connection: str = "deribit-c1",
):
    data = {
        "type": message_type,
        "timestamp": 1_700_000_000_000,
        "instrument_name": "BTC-30DEC26-100000-C",
        "change_id": change_id,
        "bids": [["new", 0.05, 1.25]],
        "asks": [],
    }
    if previous is not None:
        data["prev_change_id"] = previous
    payload = {
        "jsonrpc": "2.0",
        "method": "subscription",
        "params": {
            "channel": "book.BTC-30DEC26-100000-C.100ms",
            "data": data,
        },
    }
    return parse_deribit_message(
        json.dumps(payload, separators=(",", ":")),
        receive_ts_ns=1_700_000_000_001_000_000 + change_id,
        receive_sequence=change_id,
        connection_id=connection,
    )


def test_deribit_book_envelope_preserves_payload_and_change_id() -> None:
    event = _book("snapshot", 100)

    assert event.exchange == "deribit"
    assert event.market_type == "option"
    assert event.channel == "orderbook"
    assert event.symbol == "BTC-30DEC26-100000-C"
    assert event.message_type == "snapshot"
    assert event.sequence == 100
    assert event.update_id == 100
    assert event.payload_sha256 == hashlib.sha256(event.payload_text.encode("utf-8")).hexdigest()


def test_deribit_json_rpc_response_remains_control() -> None:
    event = parse_deribit_message(
        '{"jsonrpc":"2.0","id":42,"result":["book.BTC-PERPETUAL.100ms"]}',
        receive_ts_ns=1,
        connection_id="c",
    )

    assert event.channel == "control"
    assert event.symbol == "ALL"


def test_deribit_book_gate_enforces_snapshot_continuity_and_connection() -> None:
    gate = DeribitBookSequenceGate("BTC-30DEC26-100000-C")

    with pytest.raises(DeribitSnapshotRequired, match="fresh snapshot"):
        gate.apply(_book("change", 101, 100))
    assert gate.apply(_book("snapshot", 100)) is True
    assert gate.apply(_book("change", 101, 100)) is True
    with pytest.raises(DeribitSequenceGap, match="prev_change_id=101"):
        gate.apply(_book("change", 103, 99))

    gate.apply(_book("snapshot", 200))
    with pytest.raises(DeribitSnapshotRequired, match="connection changed"):
        gate.apply(_book("change", 201, 200, connection="deribit-c2"))


def test_deribit_parser_rejects_invalid_shapes() -> None:
    with pytest.raises(RawEventError, match="not valid JSON"):
        parse_deribit_message("bad", receive_ts_ns=1, connection_id="c")
    with pytest.raises(RawEventError, match="JSON object"):
        parse_deribit_message("[]", receive_ts_ns=1, connection_id="c")
    with pytest.raises(RawEventError, match="params must be"):
        parse_deribit_message('{"params":[]}', receive_ts_ns=1, connection_id="c")
