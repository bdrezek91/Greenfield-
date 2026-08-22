"""Versioned, venue-preserving envelope for Bronze market data.

The payload is the exact UTF-8 WebSocket text received from the venue.  It is
hashed before any parser or normalizer sees it, so later schema migrations can
always start again from the original message rather than a lossy projection.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from typing import Any

RAW_EVENT_SCHEMA_VERSION = 1
RAW_INGESTION_VERSION = "greenfield-bybit-raw-v1"


class RawEventError(ValueError):
    """The transport message cannot satisfy the raw-event contract."""


@dataclass(frozen=True, slots=True)
class RawMarketEvent:
    schema_version: int
    ingestion_version: str
    event_id: str
    exchange: str
    market_type: str
    channel: str
    topic: str
    symbol: str
    message_type: str
    exchange_ts_ms: int | None
    receive_ts_ns: int
    receive_sequence: int
    matching_ts_ms: int | None
    sequence: int | None
    update_id: int | None
    connection_id: str
    payload_sha256: str
    payload_text: str

    def __post_init__(self) -> None:
        if self.schema_version != RAW_EVENT_SCHEMA_VERSION:
            raise RawEventError(f"unsupported raw schema version: {self.schema_version}")
        if self.receive_ts_ns <= 0:
            raise RawEventError("receive_ts_ns must be positive")
        if self.receive_sequence <= 0:
            raise RawEventError("receive_sequence must be positive")
        if not self.connection_id:
            raise RawEventError("connection_id is required")
        actual_hash = hashlib.sha256(self.payload_text.encode("utf-8")).hexdigest()
        if actual_hash != self.payload_sha256:
            raise RawEventError("payload_sha256 does not match payload_text")

    def to_record(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_record(cls, record: dict[str, Any]) -> RawMarketEvent:
        cleaned = dict(record)
        for name in ("exchange_ts_ms", "matching_ts_ms", "sequence", "update_id"):
            value = cleaned.get(name)
            if value is not None:
                cleaned[name] = int(value)
        cleaned["schema_version"] = int(cleaned["schema_version"])
        cleaned["receive_ts_ns"] = int(cleaned["receive_ts_ns"])
        cleaned["receive_sequence"] = int(cleaned["receive_sequence"])
        return cls(**cleaned)

    def payload(self) -> dict[str, Any]:
        value = json.loads(self.payload_text)
        if not isinstance(value, dict):
            raise RawEventError("raw market payload must be a JSON object")
        return value


def parse_bybit_message(
    payload_text: str,
    *,
    receive_ts_ns: int,
    connection_id: str,
    market_type: str = "linear",
    receive_sequence: int = 1,
) -> RawMarketEvent:
    """Wrap one exact Bybit WebSocket message without dropping venue fields."""
    try:
        message = json.loads(payload_text)
    except json.JSONDecodeError as exc:
        raise RawEventError("Bybit WebSocket payload is not valid JSON") from exc
    if not isinstance(message, dict):
        raise RawEventError("Bybit WebSocket payload must be a JSON object")

    topic = str(message.get("topic", ""))
    data = message.get("data")
    first_data = _first_mapping(data)
    channel = _bybit_channel(topic)
    symbol = _bybit_symbol(topic, first_data)
    message_type = str(message.get("type") or message.get("op") or "control")

    sequence = _optional_int(message.get("cs"))
    if sequence is None:
        sequence = _optional_int(first_data.get("seq"))

    update_id = _optional_int(first_data.get("u"))
    exchange_ts_ms = _optional_int(message.get("ts"))
    matching_ts_ms = _optional_int(message.get("cts"))
    payload_sha256 = hashlib.sha256(payload_text.encode("utf-8")).hexdigest()
    identity = "|".join(
        (
            "bybit",
            market_type,
            connection_id,
            str(receive_ts_ns),
            str(receive_sequence),
            topic,
            payload_sha256,
        )
    )
    event_id = hashlib.sha256(identity.encode("utf-8")).hexdigest()

    return RawMarketEvent(
        schema_version=RAW_EVENT_SCHEMA_VERSION,
        ingestion_version=RAW_INGESTION_VERSION,
        event_id=event_id,
        exchange="bybit",
        market_type=market_type,
        channel=channel,
        topic=topic,
        symbol=symbol,
        message_type=message_type,
        exchange_ts_ms=exchange_ts_ms,
        receive_ts_ns=receive_ts_ns,
        receive_sequence=receive_sequence,
        matching_ts_ms=matching_ts_ms,
        sequence=sequence,
        update_id=update_id,
        connection_id=connection_id,
        payload_sha256=payload_sha256,
        payload_text=payload_text,
    )


def _first_mapping(data: Any) -> dict[str, Any]:
    if isinstance(data, dict):
        return data
    if isinstance(data, list) and data and isinstance(data[0], dict):
        return data[0]
    return {}


def _optional_int(value: Any) -> int | None:
    if value is None or value == "":
        return None
    try:
        return int(value)
    except (TypeError, ValueError) as exc:
        raise RawEventError(f"expected integer metadata, received {value!r}") from exc


def _bybit_channel(topic: str) -> str:
    if topic.startswith("orderbook."):
        return "orderbook"
    if topic.startswith("publicTrade."):
        return "trades"
    if topic.startswith("allLiquidation."):
        return "liquidations"
    if topic.startswith("tickers."):
        return "ticker"
    if topic:
        return topic.split(".", maxsplit=1)[0]
    return "control"


def _bybit_symbol(topic: str, data: dict[str, Any]) -> str:
    candidate = data.get("s") or data.get("symbol")
    if candidate:
        return str(candidate)
    if topic:
        return topic.rsplit(".", maxsplit=1)[-1]
    return "ALL"
