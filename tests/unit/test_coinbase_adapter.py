from __future__ import annotations

import hashlib
import json

import pytest

from src.data.coinbase_adapter import (
    CoinbaseConnectionSequenceGate,
    CoinbaseLevel2SequenceGate,
    CoinbaseReplayError,
    CoinbaseSequenceDuplicate,
    CoinbaseSequenceGap,
    CoinbaseSequenceRollback,
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


def _msg(
    channel: str,
    sequence: int | None,
    *,
    connection: str = "coinbase-c1",
    product_id: str | None = "BTC-USD",
):
    events = [{"type": "update", "product_id": product_id, "updates": []}] if product_id else []
    payload: dict = {
        "channel": channel,
        "timestamp": "2023-02-09T20:32:50.714964855Z",
        "events": events,
    }
    if sequence is not None:
        payload["sequence_num"] = sequence
    return parse_coinbase_message(
        json.dumps(payload, separators=(",", ":")),
        receive_ts_ns=1,
        connection_id=connection,
    )


def test_connection_gate_bootstraps_from_an_arbitrary_first_sequence_num() -> None:
    """Must not assume the counter starts at 0."""
    gate = CoinbaseConnectionSequenceGate()
    assert gate.last_sequence is None

    assert gate.observe(_msg("l2_data", 4_815_162_342)) is True

    assert gate.connection_id == "coinbase-c1"
    assert gate.last_sequence == 4_815_162_342


def test_connection_gate_accepts_a_valid_sequence_across_channels_and_products() -> None:
    """One counter shared by every channel and every product on the
    connection - the real, probed Coinbase behavior."""
    gate = CoinbaseConnectionSequenceGate()

    assert gate.observe(_msg("subscriptions", 100, product_id=None)) is True
    assert gate.observe(_msg("l2_data", 101, product_id="BTC-USD")) is True
    assert gate.observe(_msg("market_trades", 102, product_id="ETH-USD")) is True
    assert gate.observe(_msg("ticker", 103, product_id="BTC-USD")) is True
    assert gate.observe(_msg("l2_data", 104, product_id="ETH-USD")) is True

    assert gate.last_sequence == 104


def test_connection_gate_ignores_messages_without_a_sequence_num() -> None:
    gate = CoinbaseConnectionSequenceGate()
    gate.observe(_msg("l2_data", 10))

    assert gate.observe(_msg("heartbeats", None, product_id=None)) is False

    assert gate.last_sequence == 10  # unaffected


def test_connection_gate_detects_a_forward_gap() -> None:
    gate = CoinbaseConnectionSequenceGate()
    gate.observe(_msg("l2_data", 10))

    with pytest.raises(CoinbaseSequenceGap, match="expected 11, observed 13") as excinfo:
        gate.observe(_msg("market_trades", 13))
    assert "2 missing" in str(excinfo.value)
    # fail-closed: state resets rather than silently continuing from 13
    assert gate.last_sequence is None
    assert gate.connection_id is None


def test_connection_gate_detects_an_exact_duplicate() -> None:
    gate = CoinbaseConnectionSequenceGate()
    gate.observe(_msg("l2_data", 10))
    gate.observe(_msg("market_trades", 11))

    with pytest.raises(CoinbaseSequenceDuplicate, match="duplicate sequence_num=11"):
        gate.observe(_msg("ticker", 11))
    assert gate.last_sequence is None


def test_connection_gate_detects_a_rollback() -> None:
    gate = CoinbaseConnectionSequenceGate()
    gate.observe(_msg("l2_data", 10))
    gate.observe(_msg("market_trades", 11))
    gate.observe(_msg("ticker", 12))

    with pytest.raises(CoinbaseSequenceRollback, match="last 12, observed 5"):
        gate.observe(_msg("l2_data", 5))
    assert gate.last_sequence is None


def test_connection_gate_resets_cleanly_on_reconnect_rather_than_flagging_a_rollback() -> None:
    gate = CoinbaseConnectionSequenceGate()
    gate.observe(_msg("l2_data", 500, connection="conn-a"))
    gate.observe(_msg("market_trades", 501, connection="conn-a"))

    # a fresh connection legitimately starts its own low counter - must not
    # be mistaken for a rollback of conn-a's counter
    result = gate.observe(_msg("l2_data", 3, connection="conn-b"))

    assert result is True
    assert gate.connection_id == "conn-b"
    assert gate.last_sequence == 3
    # and continues normally from there
    assert gate.observe(_msg("ticker", 4, connection="conn-b")) is True


def test_connection_gate_rejects_non_coinbase_events() -> None:
    gate = CoinbaseConnectionSequenceGate()
    okx_like = parse_coinbase_message(
        json.dumps({"channel": "l2_data", "sequence_num": 1, "events": []}),
        receive_ts_ns=1,
        connection_id="c",
    )
    object.__setattr__(okx_like, "exchange", "okx")

    with pytest.raises(CoinbaseReplayError, match="only Coinbase events"):
        gate.observe(okx_like)


def test_connection_gate_recovers_after_an_error_via_a_fresh_instance() -> None:
    """Fail-closed after continuity loss: a caller that reacts to the raised
    error by starting a new connection (as RawCoinbaseCollector does) gets
    a clean, correctly-bootstrapping gate - state does not stay corrupted."""
    gate = CoinbaseConnectionSequenceGate()
    gate.observe(_msg("l2_data", 10))
    with pytest.raises(CoinbaseSequenceGap):
        gate.observe(_msg("l2_data", 12))

    fresh = CoinbaseConnectionSequenceGate()
    assert fresh.observe(_msg("l2_data", 999, connection="conn-new")) is True


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
