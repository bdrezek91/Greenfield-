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
