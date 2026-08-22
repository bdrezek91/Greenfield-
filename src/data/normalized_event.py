"""Deterministic Bronze-to-Silver normalization for Bybit raw events.

The Bronze envelope remains the source of truth.  Silver rows keep explicit
lineage back to the raw event and retain decimal venue values as strings so
normalization cannot introduce floating-point drift before feature building.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable
from dataclasses import asdict, dataclass
from decimal import Decimal, InvalidOperation
from typing import Any

from src.data.raw_event import RawMarketEvent

NORMALIZED_EVENT_SCHEMA_VERSION = 1
NORMALIZER_VERSION = "greenfield-bybit-normalizer-v1"
_CHANNELS = {"orderbook", "trades", "liquidations", "ticker"}


class NormalizationError(ValueError):
    """A raw venue message cannot be mapped without guessing."""


@dataclass(frozen=True, slots=True)
class NormalizedMarketEvent:
    schema_version: int
    normalizer_version: str
    normalized_id: str
    raw_event_id: str
    raw_payload_sha256: str
    exchange: str
    market_type: str
    channel: str
    record_type: str
    symbol: str
    event_ts_ms: int
    receive_ts_ns: int
    receive_sequence: int
    connection_id: str
    message_type: str
    sequence: int | None
    update_id: int | None
    row_index: int
    side: str | None = None
    price: str | None = None
    size: str | None = None
    trade_id: str | None = None
    tick_direction: str | None = None
    is_block_trade: bool | None = None
    is_rpi_trade: bool | None = None
    book_side: str | None = None
    book_action: str | None = None
    metric_name: str | None = None
    metric_value: str | None = None

    def __post_init__(self) -> None:
        if self.schema_version != NORMALIZED_EVENT_SCHEMA_VERSION:
            raise NormalizationError("unsupported normalized schema version")
        if self.channel not in _CHANNELS:
            raise NormalizationError(f"unsupported normalized channel: {self.channel}")
        if self.event_ts_ms <= 0 or self.receive_ts_ns <= 0:
            raise NormalizationError("timestamps must be positive")
        if self.row_index < 0:
            raise NormalizationError("row_index must be non-negative")
        if not self.normalized_id or not self.raw_event_id or not self.raw_payload_sha256:
            raise NormalizationError("normalized lineage is required")

    def to_record(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class NormalizationReport:
    raw_event_count: int
    normalized_row_count: int
    skipped_control_count: int
    raw_channel_counts: dict[str, int]
    normalized_record_counts: dict[str, int]
    normalized_ids_sha256: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def normalize_bybit_event(event: RawMarketEvent) -> tuple[NormalizedMarketEvent, ...]:
    """Normalize one immutable Bybit raw event, failing closed on bad shapes."""
    if event.exchange != "bybit":
        raise NormalizationError(f"expected Bybit event, received {event.exchange!r}")
    if event.channel == "control":
        return ()
    if event.channel not in _CHANNELS:
        raise NormalizationError(f"unsupported Bybit channel: {event.channel!r}")

    message = event.payload()
    if event.channel == "orderbook":
        records = _normalize_orderbook(event, message)
    elif event.channel == "trades":
        records = _normalize_trades(event, message)
    elif event.channel == "liquidations":
        records = _normalize_liquidations(event, message)
    else:
        records = _normalize_ticker(event, message)
    return tuple(_build_event(event, index, **record) for index, record in enumerate(records))


def normalize_bybit_events(
    events: Iterable[RawMarketEvent],
) -> tuple[list[NormalizedMarketEvent], NormalizationReport]:
    """Normalize a stream in deterministic receive order and return its audit report."""
    ordered = sorted(
        events,
        key=lambda event: (event.receive_ts_ns, event.receive_sequence, event.event_id),
    )
    rows: list[NormalizedMarketEvent] = []
    raw_channel_counts: dict[str, int] = {}
    record_counts: dict[str, int] = {}
    skipped_control_count = 0
    for event in ordered:
        raw_channel_counts[event.channel] = raw_channel_counts.get(event.channel, 0) + 1
        normalized = normalize_bybit_event(event)
        if event.channel == "control":
            skipped_control_count += 1
        for row in normalized:
            rows.append(row)
            record_counts[row.record_type] = record_counts.get(row.record_type, 0) + 1
    digest = hashlib.sha256("\n".join(row.normalized_id for row in rows).encode("ascii"))
    return rows, NormalizationReport(
        raw_event_count=len(ordered),
        normalized_row_count=len(rows),
        skipped_control_count=skipped_control_count,
        raw_channel_counts=dict(sorted(raw_channel_counts.items())),
        normalized_record_counts=dict(sorted(record_counts.items())),
        normalized_ids_sha256=digest.hexdigest(),
    )


def _normalize_orderbook(event: RawMarketEvent, message: dict[str, Any]) -> list[dict[str, Any]]:
    data = _mapping(message.get("data"), "orderbook data")
    message_type = str(message.get("type", ""))
    if message_type not in {"snapshot", "delta"}:
        raise NormalizationError(f"invalid orderbook message type: {message_type!r}")
    event_ts_ms = event.matching_ts_ms or event.exchange_ts_ms
    if event_ts_ms is None:
        raise NormalizationError("orderbook event timestamp is missing")
    records = []
    for book_side, field in (("bid", "b"), ("ask", "a")):
        levels = data.get(field)
        if not isinstance(levels, list):
            raise NormalizationError(f"orderbook {field} must be a list")
        for level in levels:
            if not isinstance(level, list) or len(level) != 2:
                raise NormalizationError(f"invalid orderbook level: {level!r}")
            price = _decimal_text(level[0], positive=True, name="price")
            size = _decimal_text(level[1], positive=False, name="size")
            records.append(
                {
                    "record_type": "book_level",
                    "event_ts_ms": event_ts_ms,
                    "book_side": book_side,
                    "book_action": "delete" if Decimal(size) == 0 else "upsert",
                    "price": price,
                    "size": size,
                }
            )
    return records


def _normalize_trades(event: RawMarketEvent, message: dict[str, Any]) -> list[dict[str, Any]]:
    data = _list_of_mappings(message.get("data"), "trade data")
    records = []
    for entry in data:
        side = _side(entry.get("S"))
        records.append(
            {
                "record_type": "trade",
                "event_ts_ms": _positive_int(entry.get("T"), "trade timestamp"),
                "side": side,
                "price": _decimal_text(entry.get("p"), positive=True, name="price"),
                "size": _decimal_text(entry.get("v"), positive=True, name="size"),
                "trade_id": _required_text(entry.get("i"), "trade id"),
                "tick_direction": _optional_text(entry.get("L")),
                "is_block_trade": _optional_bool(entry.get("BT")),
                "is_rpi_trade": _optional_bool(entry.get("RPI")),
            }
        )
    return records


def _normalize_liquidations(
    event: RawMarketEvent, message: dict[str, Any]
) -> list[dict[str, Any]]:
    data = _list_of_mappings(message.get("data"), "liquidation data")
    return [
        {
            "record_type": "liquidation",
            "event_ts_ms": _positive_int(entry.get("T"), "liquidation timestamp"),
            "side": _side(entry.get("S")),
            "price": _decimal_text(entry.get("p"), positive=True, name="price"),
            "size": _decimal_text(entry.get("v"), positive=True, name="size"),
        }
        for entry in data
    ]


def _normalize_ticker(event: RawMarketEvent, message: dict[str, Any]) -> list[dict[str, Any]]:
    data = _mapping(message.get("data"), "ticker data")
    if event.exchange_ts_ms is None:
        raise NormalizationError("ticker event timestamp is missing")
    records = []
    for name in sorted(data):
        if name in {"s", "symbol"}:
            continue
        records.append(
            {
                "record_type": "ticker_metric",
                "event_ts_ms": event.exchange_ts_ms,
                "metric_name": str(name),
                "metric_value": _stable_value(data[name]),
            }
        )
    return records


def _build_event(
    raw: RawMarketEvent, row_index: int, **values: Any
) -> NormalizedMarketEvent:
    normalized_id = hashlib.sha256(
        f"{NORMALIZER_VERSION}|{raw.event_id}|{row_index}".encode("ascii")
    ).hexdigest()
    return NormalizedMarketEvent(
        schema_version=NORMALIZED_EVENT_SCHEMA_VERSION,
        normalizer_version=NORMALIZER_VERSION,
        normalized_id=normalized_id,
        raw_event_id=raw.event_id,
        raw_payload_sha256=raw.payload_sha256,
        exchange=raw.exchange,
        market_type=raw.market_type,
        channel=raw.channel,
        symbol=raw.symbol,
        receive_ts_ns=raw.receive_ts_ns,
        receive_sequence=raw.receive_sequence,
        connection_id=raw.connection_id,
        message_type=raw.message_type,
        sequence=raw.sequence,
        update_id=raw.update_id,
        row_index=row_index,
        **values,
    )


def _mapping(value: Any, name: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise NormalizationError(f"{name} must be an object")
    return value


def _list_of_mappings(value: Any, name: str) -> list[dict[str, Any]]:
    if not isinstance(value, list) or any(not isinstance(item, dict) for item in value):
        raise NormalizationError(f"{name} must be a list of objects")
    return value


def _decimal_text(value: Any, *, positive: bool, name: str) -> str:
    try:
        number = Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise NormalizationError(f"invalid {name}: {value!r}") from exc
    if not number.is_finite() or number < 0 or (positive and number <= 0):
        raise NormalizationError(f"invalid {name}: {value!r}")
    return format(number, "f")


def _positive_int(value: Any, name: str) -> int:
    if isinstance(value, bool):
        raise NormalizationError(f"invalid {name}: {value!r}")
    try:
        result = int(value)
    except (TypeError, ValueError) as exc:
        raise NormalizationError(f"invalid {name}: {value!r}") from exc
    if result <= 0:
        raise NormalizationError(f"invalid {name}: {value!r}")
    return result


def _side(value: Any) -> str:
    side = _required_text(value, "side").lower()
    if side not in {"buy", "sell"}:
        raise NormalizationError(f"invalid side: {value!r}")
    return side


def _required_text(value: Any, name: str) -> str:
    result = str(value or "")
    if not result:
        raise NormalizationError(f"{name} is required")
    return result


def _optional_text(value: Any) -> str | None:
    return None if value is None else str(value)


def _optional_bool(value: Any) -> bool | None:
    if value is None:
        return None
    if not isinstance(value, bool):
        raise NormalizationError(f"expected boolean, received {value!r}")
    return value


def _stable_value(value: Any) -> str:
    if isinstance(value, str):
        return value
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
