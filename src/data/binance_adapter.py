"""Lossless Binance USD-M raw envelope and depth sequence gate.

Payload fields follow Binance's public aggregate-trade and diff-depth stream
contracts. The exact received JSON remains the Bronze source of truth.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any

from src.data.raw_event import RAW_EVENT_SCHEMA_VERSION, RawEventError, RawMarketEvent

BINANCE_RAW_INGESTION_VERSION = "greenfield-binance-raw-v1"


def parse_binance_message(
    payload_text: str,
    *,
    receive_ts_ns: int,
    connection_id: str,
    market_type: str = "linear",
    receive_sequence: int = 1,
) -> RawMarketEvent:
    """Wrap a raw or combined Binance stream payload without rewriting it."""
    try:
        outer = json.loads(payload_text)
    except json.JSONDecodeError as exc:
        raise RawEventError("Binance WebSocket payload is not valid JSON") from exc
    if not isinstance(outer, dict):
        raise RawEventError("Binance WebSocket payload must be a JSON object")
    stream = str(outer.get("stream", ""))
    candidate = outer.get("data", outer)
    if not isinstance(candidate, dict):
        raise RawEventError("Binance combined stream data must be an object")
    message = candidate
    event_type = str(message.get("e", ""))
    channel = _channel(event_type)
    symbol = str(message.get("s") or "ALL")
    topic = stream or _topic(symbol, event_type)
    exchange_ts_ms = _optional_int(message.get("E"))
    matching_ts_ms = _optional_int(message.get("T"))
    sequence = _optional_int(message.get("U"))
    update_id = _optional_int(message.get("u"))
    if channel == "trades":
        sequence = _optional_int(message.get("a") or message.get("t"))
    if channel == "control":
        message_type = str(message.get("method") or "control")
    else:
        message_type = "delta"
    payload_sha256 = hashlib.sha256(payload_text.encode("utf-8")).hexdigest()
    identity = "|".join(
        (
            "binance",
            market_type,
            connection_id,
            str(receive_ts_ns),
            str(receive_sequence),
            topic,
            payload_sha256,
        )
    )
    return RawMarketEvent(
        schema_version=RAW_EVENT_SCHEMA_VERSION,
        ingestion_version=BINANCE_RAW_INGESTION_VERSION,
        event_id=hashlib.sha256(identity.encode("utf-8")).hexdigest(),
        exchange="binance",
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


class BinanceReplayError(RuntimeError):
    pass


class BinanceSnapshotRequired(BinanceReplayError):
    pass


class BinanceSequenceGap(BinanceReplayError):
    pass


@dataclass(slots=True)
class BinanceDepthSequenceGate:
    """Validate REST-snapshot bridging and `pu` continuity before L2 replay."""

    symbol: str
    update_id: int | None = None
    connection_id: str | None = None
    _first_stream_event: bool = True

    def bootstrap(self, *, snapshot_update_id: int, connection_id: str) -> None:
        if snapshot_update_id <= 0 or not connection_id:
            raise ValueError("valid snapshot update ID and connection are required")
        self.update_id = snapshot_update_id
        self.connection_id = connection_id
        self._first_stream_event = True

    def invalidate(self) -> None:
        self.update_id = None
        self.connection_id = None
        self._first_stream_event = True

    def apply(self, event: RawMarketEvent) -> bool:
        if event.exchange != "binance" or event.channel != "orderbook":
            raise BinanceReplayError("depth gate accepts only Binance orderbook events")
        if event.symbol != self.symbol:
            raise BinanceReplayError(f"gate {self.symbol} cannot accept {event.symbol}")
        if self.update_id is None or self.connection_id is None:
            raise BinanceSnapshotRequired(f"{self.symbol} requires a REST depth snapshot")
        if event.connection_id != self.connection_id:
            self.invalidate()
            raise BinanceSnapshotRequired(f"{self.symbol} connection changed")
        message = _stream_message(event.payload())
        first_update = _required_int(message.get("U"), "U")
        final_update = _required_int(message.get("u"), "u")
        previous_final = _required_int(message.get("pu"), "pu")
        if first_update > final_update:
            self.invalidate()
            raise BinanceSequenceGap(f"{self.symbol} invalid update range")
        if final_update <= self.update_id:
            return False
        if self._first_stream_event:
            expected = self.update_id + 1
            if not first_update <= expected <= final_update:
                self.invalidate()
                raise BinanceSequenceGap(
                    f"{self.symbol} snapshot bridge missing expected update {expected}"
                )
            self._first_stream_event = False
        elif previous_final != self.update_id:
            expected = self.update_id
            self.invalidate()
            raise BinanceSequenceGap(
                f"{self.symbol} expected pu={expected}, observed pu={previous_final}"
            )
        self.update_id = final_update
        return True


def _stream_message(payload: dict[str, Any]) -> dict[str, Any]:
    data = payload.get("data", payload)
    if not isinstance(data, dict):
        raise BinanceReplayError("combined stream data must be an object")
    return data


def _channel(event_type: str) -> str:
    if event_type == "depthUpdate":
        return "orderbook"
    if event_type in {"aggTrade", "trade"}:
        return "trades"
    if event_type in {"markPriceUpdate", "24hrTicker", "bookTicker"}:
        return "ticker"
    return "control"


def _topic(symbol: str, event_type: str) -> str:
    return f"{symbol.lower()}@{event_type}" if event_type else "control"


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
        raise BinanceReplayError(f"depth event lacks integer {name}")
    return result
