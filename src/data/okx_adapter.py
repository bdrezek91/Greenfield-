"""Lossless OKX public-stream envelope and seqId/prevSeqId replay gate."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any

from src.data.raw_event import RAW_EVENT_SCHEMA_VERSION, RawEventError, RawMarketEvent

OKX_RAW_INGESTION_VERSION = "greenfield-okx-raw-v1"


def parse_okx_message(
    payload_text: str,
    *,
    receive_ts_ns: int,
    connection_id: str,
    market_type: str = "swap",
    receive_sequence: int = 1,
) -> RawMarketEvent:
    try:
        message = json.loads(payload_text)
    except json.JSONDecodeError as exc:
        raise RawEventError("OKX WebSocket payload is not valid JSON") from exc
    if not isinstance(message, dict):
        raise RawEventError("OKX WebSocket payload must be a JSON object")
    argument = message.get("arg", {})
    if not isinstance(argument, dict):
        raise RawEventError("OKX arg must be an object")
    control_event = str(message.get("event") or "")
    topic = str(argument.get("channel") or control_event or "control")
    symbol = str(argument.get("instId") or "ALL")
    channel = "control" if control_event else _channel(topic)
    data = message.get("data")
    first = data[0] if isinstance(data, list) and data and isinstance(data[0], dict) else {}
    exchange_ts_ms = _optional_int(first.get("ts"))
    sequence = _optional_int(first.get("seqId"))
    message_type = {"snapshot": "snapshot", "update": "delta"}.get(
        str(message.get("action")),
        str(message.get("event") or "control"),
    )
    payload_hash = hashlib.sha256(payload_text.encode("utf-8")).hexdigest()
    identity = "|".join(
        (
            "okx",
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
        ingestion_version=OKX_RAW_INGESTION_VERSION,
        event_id=hashlib.sha256(identity.encode()).hexdigest(),
        exchange="okx",
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


class OkxReplayError(RuntimeError):
    pass


class OkxSnapshotRequired(OkxReplayError):
    pass


class OkxSequenceGap(OkxReplayError):
    pass


@dataclass(slots=True)
class OkxSequenceGate:
    """Require a fresh snapshot and strict ``prevSeqId`` continuity per connection."""

    symbol: str
    sequence: int | None = None
    connection_id: str | None = None

    def invalidate(self) -> None:
        self.sequence = None
        self.connection_id = None

    def apply(self, event: RawMarketEvent) -> bool:
        if event.exchange != "okx" or event.channel != "orderbook":
            raise OkxReplayError("OKX gate accepts only orderbook events")
        if event.symbol != self.symbol:
            raise OkxReplayError(f"gate {self.symbol} cannot accept {event.symbol}")
        if self.connection_id is not None and event.connection_id != self.connection_id:
            self.invalidate()
            raise OkxSnapshotRequired(f"{self.symbol} connection changed")
        message = event.payload()
        data = _first_data(message)
        sequence = _required_int(data.get("seqId"), "seqId")
        previous = _required_int(data.get("prevSeqId"), "prevSeqId")
        if event.message_type == "snapshot":
            self.sequence = sequence
            self.connection_id = event.connection_id
            return True
        if event.message_type != "delta" or self.sequence is None:
            raise OkxSnapshotRequired(f"{self.symbol} requires a fresh snapshot")
        if previous != self.sequence:
            expected = self.sequence
            self.invalidate()
            raise OkxSequenceGap(
                f"{self.symbol} expected prevSeqId={expected}, observed {previous}"
            )
        if sequence < previous:
            self.invalidate()
            raise OkxSequenceGap(f"{self.symbol} seqId regressed")
        heartbeat = sequence == previous and not data.get("bids") and not data.get("asks")
        self.sequence = sequence
        return not heartbeat


def _first_data(message: dict[str, Any]) -> dict[str, Any]:
    data = message.get("data")
    if not isinstance(data, list) or len(data) != 1 or not isinstance(data[0], dict):
        raise OkxReplayError("OKX book message must contain one data object")
    return data[0]


def _channel(topic: str) -> str:
    if topic.startswith("books") or topic == "bbo-tbt":
        return "orderbook"
    if topic.startswith("trades"):
        return "trades"
    if topic in {"tickers", "mark-price", "index-tickers", "funding-rate"}:
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
        raise OkxReplayError(f"OKX message lacks {name}")
    return result
