"""Lossless Deribit JSON-RPC public-stream envelope and order-book gate."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any

from src.data.raw_event import RAW_EVENT_SCHEMA_VERSION, RawEventError, RawMarketEvent

DERIBIT_RAW_INGESTION_VERSION = "greenfield-deribit-raw-v1"


def parse_deribit_message(
    payload_text: str,
    *,
    receive_ts_ns: int,
    connection_id: str,
    market_type: str = "option",
    receive_sequence: int = 1,
) -> RawMarketEvent:
    """Wrap one exact public subscription notification or control response."""
    try:
        message = json.loads(payload_text)
    except json.JSONDecodeError as exc:
        raise RawEventError("Deribit WebSocket payload is not valid JSON") from exc
    if not isinstance(message, dict):
        raise RawEventError("Deribit WebSocket payload must be a JSON object")
    params = message.get("params", {})
    if not isinstance(params, dict):
        raise RawEventError("Deribit params must be an object")
    is_subscription = message.get("method") == "subscription"
    topic = str(params.get("channel") or message.get("method") or "control")
    channel = _channel(topic) if is_subscription else "control"
    data = params.get("data")
    products = _products(data)
    symbol = next(iter(products)) if len(products) == 1 else ("ALL" if not products else "MULTI")
    exchange_ts_ms = _exchange_timestamp(data)
    sequence = _book_int(data, "change_id") if channel == "orderbook" else None
    if channel == "orderbook" and isinstance(data, dict):
        message_type = {"snapshot": "snapshot", "change": "delta"}.get(
            str(data.get("type")), "batch"
        )
    elif channel == "control":
        message_type = "control"
    else:
        message_type = "delta"
    payload_hash = hashlib.sha256(payload_text.encode("utf-8")).hexdigest()
    identity = "|".join(
        (
            "deribit",
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
        ingestion_version=DERIBIT_RAW_INGESTION_VERSION,
        event_id=hashlib.sha256(identity.encode("utf-8")).hexdigest(),
        exchange="deribit",
        market_type=market_type,
        channel=channel,
        topic=topic,
        symbol=symbol,
        message_type=message_type,
        exchange_ts_ms=exchange_ts_ms,
        receive_ts_ns=receive_ts_ns,
        receive_sequence=receive_sequence,
        matching_ts_ms=None,
        sequence=sequence,
        update_id=sequence,
        connection_id=connection_id,
        payload_sha256=payload_hash,
        payload_text=payload_text,
    )


class DeribitReplayError(RuntimeError):
    pass


class DeribitSnapshotRequired(DeribitReplayError):
    pass


class DeribitSequenceGap(DeribitReplayError):
    pass


@dataclass(slots=True)
class DeribitBookSequenceGate:
    """Require a connection-scoped snapshot and strict change-ID continuity."""

    symbol: str
    change_id: int | None = None
    connection_id: str | None = None

    def invalidate(self) -> None:
        self.change_id = None
        self.connection_id = None

    def apply(self, event: RawMarketEvent) -> bool:
        if event.exchange != "deribit" or event.channel != "orderbook":
            raise DeribitReplayError("Deribit gate accepts only orderbook events")
        if event.symbol != self.symbol:
            raise DeribitReplayError(f"gate {self.symbol} cannot accept {event.symbol}")
        if self.connection_id is not None and event.connection_id != self.connection_id:
            self.invalidate()
            raise DeribitSnapshotRequired(f"{self.symbol} connection changed")
        data = _book_data(event.payload())
        change_id = _required_int(data.get("change_id"), "change_id")
        if event.message_type == "snapshot":
            self.change_id = change_id
            self.connection_id = event.connection_id
            return True
        if event.message_type != "delta" or self.change_id is None:
            raise DeribitSnapshotRequired(f"{self.symbol} requires a fresh snapshot")
        previous = _required_int(data.get("prev_change_id"), "prev_change_id")
        if previous != self.change_id:
            expected = self.change_id
            self.invalidate()
            raise DeribitSequenceGap(
                f"{self.symbol} expected prev_change_id={expected}, observed {previous}"
            )
        if change_id <= previous:
            self.invalidate()
            raise DeribitSequenceGap(f"{self.symbol} change_id did not advance")
        self.change_id = change_id
        return True


def _book_data(message: dict[str, Any]) -> dict[str, Any]:
    params = message.get("params")
    if not isinstance(params, dict) or not isinstance(params.get("data"), dict):
        raise DeribitReplayError("Deribit book notification must contain one data object")
    return params["data"]


def _products(data: Any) -> set[str]:
    entries = data if isinstance(data, list) else [data]
    products: set[str] = set()
    for entry in entries:
        if entry is None:
            continue
        if not isinstance(entry, dict):
            raise RawEventError("Deribit subscription data must be an object or list of objects")
        if entry.get("instrument_name"):
            products.add(str(entry["instrument_name"]))
    return products


def _exchange_timestamp(data: Any) -> int | None:
    entry = data[0] if isinstance(data, list) and data else data
    if entry is None:
        return None
    if not isinstance(entry, dict):
        raise RawEventError("Deribit subscription data must contain objects")
    return _optional_int(entry.get("timestamp"))


def _book_int(data: Any, name: str) -> int | None:
    if not isinstance(data, dict):
        raise RawEventError("Deribit book data must be an object")
    return _optional_int(data.get(name))


def _channel(topic: str) -> str:
    if topic.startswith("book."):
        return "orderbook"
    if topic.startswith("trades."):
        return "trades"
    if topic.startswith("ticker."):
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


def _required_int(value: Any, name: str) -> int:
    result = _optional_int(value)
    if result is None:
        raise DeribitReplayError(f"Deribit message lacks {name}")
    return result
