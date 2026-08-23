"""Lossless Coinbase Advanced Trade public-stream envelope and L2 gate."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from src.data.raw_event import RAW_EVENT_SCHEMA_VERSION, RawEventError, RawMarketEvent

COINBASE_RAW_INGESTION_VERSION = "greenfield-coinbase-raw-v1"


def parse_coinbase_message(
    payload_text: str,
    *,
    receive_ts_ns: int,
    connection_id: str,
    market_type: str = "spot",
    receive_sequence: int = 1,
) -> RawMarketEvent:
    """Wrap one exact Advanced Trade message without rewriting its payload."""
    try:
        message = json.loads(payload_text)
    except json.JSONDecodeError as exc:
        raise RawEventError("Coinbase WebSocket payload is not valid JSON") from exc
    if not isinstance(message, dict):
        raise RawEventError("Coinbase WebSocket payload must be a JSON object")
    topic = str(message.get("channel") or message.get("type") or "control")
    channel = _channel(topic)
    events = message.get("events", [])
    if not isinstance(events, list) or any(not isinstance(item, dict) for item in events):
        raise RawEventError("Coinbase events must be a list of objects")
    products = _products(events)
    symbol = next(iter(products)) if len(products) == 1 else ("ALL" if not products else "MULTI")
    sequence = _optional_int(message.get("sequence_num"))
    event_types = {str(item.get("type")) for item in events if item.get("type")}
    if channel == "control":
        message_type = "control"
    elif event_types == {"snapshot"}:
        message_type = "snapshot"
    elif event_types == {"update"}:
        message_type = "delta"
    else:
        message_type = "batch"
    payload_hash = hashlib.sha256(payload_text.encode("utf-8")).hexdigest()
    identity = "|".join(
        (
            "coinbase",
            market_type,
            connection_id,
            str(receive_ts_ns),
            str(receive_sequence),
            topic,
            payload_hash,
        )
    )
    return RawMarketEvent(
        schema_version=RAW_EVENT_SCHEMA_VERSION,
        ingestion_version=COINBASE_RAW_INGESTION_VERSION,
        event_id=hashlib.sha256(identity.encode("utf-8")).hexdigest(),
        exchange="coinbase",
        market_type=market_type,
        channel=channel,
        topic=topic,
        symbol=symbol,
        message_type=message_type,
        exchange_ts_ms=_optional_timestamp_ms(message.get("timestamp")),
        receive_ts_ns=receive_ts_ns,
        receive_sequence=receive_sequence,
        matching_ts_ms=None,
        sequence=sequence,
        update_id=sequence,
        connection_id=connection_id,
        payload_sha256=payload_hash,
        payload_text=payload_text,
    )


class CoinbaseReplayError(RuntimeError):
    pass


class CoinbaseSnapshotRequired(CoinbaseReplayError):
    pass


class CoinbaseSequenceGap(CoinbaseReplayError):
    pass


class CoinbaseSequenceDuplicate(CoinbaseReplayError):
    pass


class CoinbaseSequenceRollback(CoinbaseReplayError):
    pass


@dataclass(slots=True)
class CoinbaseConnectionSequenceGate:
    """Connection-global sequence-continuity gate (Cycle 8).

    Live protocol probing (documented in
    src.data.coinbase_raw_collector's module docstring) established that
    Coinbase's `sequence_num` is a single counter shared by every message
    the exchange sends on one WebSocket connection - every channel, every
    product, including its own automatic `subscriptions` acknowledgement -
    not a per-product/per-channel stream the way `CoinbaseLevel2SequenceGate`
    above (and the equivalent per-product assumption in most exchange SDKs)
    assumes. This gate tracks exactly one running counter per connection
    instead.

    It does NOT assume the counter starts at 0: `last_sequence` is None
    until the first message carrying `sequence_num` is observed, and
    whatever value that is becomes the bootstrap point. Only messages that
    actually carry `sequence_num` participate (`observe` returns False,
    does not raise, for a message type that doesn't have one - a missing
    field is not evidence of a gap by itself).

    A `connection_id` change is a legitimate reconnect, not an anomaly:
    state resets and re-bootstraps from the new connection's first
    sequence_num rather than being compared against the old connection's
    counter. Every other discontinuity - a forward gap, an exact repeat,
    or the counter going backward without repeating - raises a distinct,
    named exception and the gate resets itself (fail-closed: the caller is
    expected to treat this as sequence-uncertain and force a reconnect,
    exactly like `src.data.okx_adapter.OkxSequenceGate` and the Bybit
    order-book replay gate already do).
    """

    connection_id: str | None = None
    last_sequence: int | None = None

    def reset(self) -> None:
        self.connection_id = None
        self.last_sequence = None

    def observe(self, event: RawMarketEvent) -> bool:
        """Returns True if `event` advanced (or bootstrapped) the counter,
        False if `event` carried no `sequence_num` and so was not checked.
        Raises CoinbaseSequenceGap/-Duplicate/-Rollback, fail-closed, for
        any other outcome.
        """
        if event.exchange != "coinbase":
            raise CoinbaseReplayError(
                "connection sequence gate accepts only Coinbase events"
            )
        if event.sequence is None:
            return False

        if self.connection_id is not None and event.connection_id != self.connection_id:
            # A reconnect starts a brand-new counter series on the
            # exchange's side - not a rollback of the old connection's.
            self.reset()

        if self.connection_id is None:
            self.connection_id = event.connection_id
            self.last_sequence = event.sequence
            return True

        assert self.last_sequence is not None
        expected = self.last_sequence + 1
        if event.sequence == expected:
            self.last_sequence = event.sequence
            return True
        if event.sequence == self.last_sequence:
            observed_connection = self.connection_id
            self.reset()
            raise CoinbaseSequenceDuplicate(
                f"duplicate sequence_num={event.sequence} on connection "
                f"{observed_connection!r}"
            )
        if event.sequence > self.last_sequence:
            missing = event.sequence - self.last_sequence - 1
            observed_last = self.last_sequence
            self.reset()
            raise CoinbaseSequenceGap(
                f"sequence gap on connection {event.connection_id!r}: expected "
                f"{observed_last + 1}, observed {event.sequence} ({missing} missing)"
            )
        observed_last = self.last_sequence
        self.reset()
        raise CoinbaseSequenceRollback(
            f"sequence rollback on connection {event.connection_id!r}: last "
            f"{observed_last}, observed {event.sequence}"
        )


@dataclass(slots=True)
class CoinbaseLevel2SequenceGate:
    """Require an L2 snapshot and consecutive per-product sequence numbers."""

    symbol: str
    sequence: int | None = None
    connection_id: str | None = None

    def invalidate(self) -> None:
        self.sequence = None
        self.connection_id = None

    def apply(self, event: RawMarketEvent) -> bool:
        if event.exchange != "coinbase" or event.channel != "orderbook":
            raise CoinbaseReplayError("Coinbase L2 gate accepts only orderbook events")
        if event.symbol != self.symbol:
            raise CoinbaseReplayError(f"gate {self.symbol} cannot accept {event.symbol}")
        if event.sequence is None:
            raise CoinbaseReplayError("Coinbase L2 message lacks sequence_num")
        if self.connection_id is not None and event.connection_id != self.connection_id:
            self.invalidate()
            raise CoinbaseSnapshotRequired(f"{self.symbol} connection changed")
        if event.message_type == "snapshot":
            self.sequence = event.sequence
            self.connection_id = event.connection_id
            return True
        if event.message_type != "delta" or self.sequence is None:
            raise CoinbaseSnapshotRequired(f"{self.symbol} requires a fresh snapshot")
        if event.sequence <= self.sequence:
            return False
        expected = self.sequence + 1
        if event.sequence != expected:
            observed = event.sequence
            self.invalidate()
            raise CoinbaseSequenceGap(
                f"{self.symbol} expected sequence_num={expected}, observed {observed}"
            )
        self.sequence = event.sequence
        return True


def _products(events: list[dict[str, Any]]) -> set[str]:
    products: set[str] = set()
    for event in events:
        if event.get("product_id"):
            products.add(str(event["product_id"]))
        for field in ("trades", "tickers"):
            entries = event.get(field, [])
            if not isinstance(entries, list):
                raise RawEventError(f"Coinbase {field} must be a list")
            for entry in entries:
                if not isinstance(entry, dict):
                    raise RawEventError(f"Coinbase {field} must contain objects")
                if entry.get("product_id"):
                    products.add(str(entry["product_id"]))
    return products


def _channel(topic: str) -> str:
    if topic in {"level2", "l2_data"}:
        return "orderbook"
    if topic == "market_trades":
        return "trades"
    if topic in {"ticker", "ticker_batch"}:
        return "ticker"
    return "control"


def _optional_int(value: Any) -> int | None:
    if value is None or value == "":
        return None
    if isinstance(value, bool):
        raise RawEventError(f"expected integer metadata, received {value!r}")
    try:
        return int(value)
    except (TypeError, ValueError) as exc:
        raise RawEventError(f"expected integer metadata, received {value!r}") from exc


def _optional_timestamp_ms(value: Any) -> int | None:
    if value is None or value == "":
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError as exc:
        raise RawEventError(f"invalid Coinbase timestamp: {value!r}") from exc
    if parsed.tzinfo is None:
        raise RawEventError("Coinbase timestamp must be timezone-aware")
    return int(parsed.timestamp() * 1000)
