"""Deterministic Binance Bronze-to-Silver trade, L2, and ticker mapping."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable
from decimal import Decimal, InvalidOperation
from typing import Any

from src.data.normalized_event import (
    BINANCE_NORMALIZER_VERSION,
    NORMALIZED_EVENT_SCHEMA_VERSION,
    NormalizationError,
    NormalizationReport,
    NormalizedMarketEvent,
)
from src.data.raw_event import RawMarketEvent


def normalize_binance_event(
    event: RawMarketEvent,
) -> tuple[NormalizedMarketEvent, ...]:
    """Normalize one immutable Binance event without discarding sequence lineage."""
    if event.exchange != "binance":
        raise NormalizationError(f"expected Binance event, received {event.exchange!r}")
    if event.channel == "control":
        return ()
    message = _stream_message(event.payload())
    if event.channel == "orderbook":
        records = _orderbook_records(event, message)
    elif event.channel == "trades":
        records = _trade_records(message)
    elif event.channel == "ticker":
        records = _ticker_records(event, message)
    else:
        raise NormalizationError(f"unsupported Binance channel: {event.channel!r}")
    return tuple(_build_event(event, index, **record) for index, record in enumerate(records))


def normalize_binance_events(
    events: Iterable[RawMarketEvent],
) -> tuple[list[NormalizedMarketEvent], NormalizationReport]:
    ordered = sorted(
        events,
        key=lambda event: (event.receive_ts_ns, event.receive_sequence, event.event_id),
    )
    rows: list[NormalizedMarketEvent] = []
    channel_counts: dict[str, int] = {}
    record_counts: dict[str, int] = {}
    skipped = 0
    for event in ordered:
        channel_counts[event.channel] = channel_counts.get(event.channel, 0) + 1
        normalized = normalize_binance_event(event)
        if event.channel == "control":
            skipped += 1
        for row in normalized:
            rows.append(row)
            record_counts[row.record_type] = record_counts.get(row.record_type, 0) + 1
    digest = hashlib.sha256("\n".join(row.normalized_id for row in rows).encode("ascii"))
    return rows, NormalizationReport(
        raw_event_count=len(ordered),
        normalized_row_count=len(rows),
        skipped_control_count=skipped,
        raw_channel_counts=dict(sorted(channel_counts.items())),
        normalized_record_counts=dict(sorted(record_counts.items())),
        normalized_ids_sha256=digest.hexdigest(),
    )


def _orderbook_records(
    event: RawMarketEvent, message: dict[str, Any]
) -> list[dict[str, Any]]:
    event_ts_ms = event.matching_ts_ms or event.exchange_ts_ms
    if event_ts_ms is None:
        raise NormalizationError("Binance depth timestamp is missing")
    first_update_id = _positive_int(message.get("U"), "U")
    update_id = _positive_int(message.get("u"), "u")
    previous_update_id = _non_negative_int(message.get("pu"), "pu")
    if first_update_id > update_id:
        raise NormalizationError("Binance depth update range is invalid")
    records = []
    for book_side, field in (("bid", "b"), ("ask", "a")):
        levels = message.get(field)
        if not isinstance(levels, list):
            raise NormalizationError(f"Binance depth {field} must be a list")
        for level in levels:
            if not isinstance(level, list) or len(level) != 2:
                raise NormalizationError(f"invalid Binance depth level: {level!r}")
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
                    "first_update_id": first_update_id,
                    "previous_update_id": previous_update_id,
                }
            )
    return records


def _trade_records(message: dict[str, Any]) -> list[dict[str, Any]]:
    event_type = message.get("e")
    if event_type not in {"aggTrade", "trade"}:
        raise NormalizationError(f"invalid Binance trade type: {event_type!r}")
    maker_flag = message.get("m")
    if not isinstance(maker_flag, bool):
        raise NormalizationError("Binance trade maker flag must be boolean")
    trade_id = message.get("a") if event_type == "aggTrade" else message.get("t")
    return [
        {
            "record_type": "trade",
            "event_ts_ms": _positive_int(message.get("T"), "trade timestamp"),
            "side": "sell" if maker_flag else "buy",
            "price": _decimal_text(message.get("p"), positive=True, name="price"),
            "size": _decimal_text(message.get("q"), positive=True, name="size"),
            "trade_id": str(_positive_int(trade_id, "trade id")),
        }
    ]


def _ticker_records(
    event: RawMarketEvent, message: dict[str, Any]
) -> list[dict[str, Any]]:
    if event.exchange_ts_ms is None:
        raise NormalizationError("Binance ticker timestamp is missing")
    ignored = {"e", "E", "s", "T"}
    return [
        {
            "record_type": "ticker_metric",
            "event_ts_ms": event.exchange_ts_ms,
            "metric_name": str(name),
            "metric_value": _stable_value(message[name]),
        }
        for name in sorted(message)
        if name not in ignored
    ]


def _build_event(
    raw: RawMarketEvent, row_index: int, **values: Any
) -> NormalizedMarketEvent:
    normalized_id = hashlib.sha256(
        f"{BINANCE_NORMALIZER_VERSION}|{raw.event_id}|{row_index}".encode("ascii")
    ).hexdigest()
    return NormalizedMarketEvent(
        schema_version=NORMALIZED_EVENT_SCHEMA_VERSION,
        normalizer_version=BINANCE_NORMALIZER_VERSION,
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


def _stream_message(payload: dict[str, Any]) -> dict[str, Any]:
    message = payload.get("data", payload)
    if not isinstance(message, dict):
        raise NormalizationError("Binance combined stream data must be an object")
    return message


def _decimal_text(value: Any, *, positive: bool, name: str) -> str:
    try:
        number = Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise NormalizationError(f"invalid {name}: {value!r}") from exc
    if not number.is_finite() or number < 0 or (positive and number <= 0):
        raise NormalizationError(f"invalid {name}: {value!r}")
    return format(number, "f")


def _positive_int(value: Any, name: str) -> int:
    result = _non_negative_int(value, name)
    if result <= 0:
        raise NormalizationError(f"invalid {name}: {value!r}")
    return result


def _non_negative_int(value: Any, name: str) -> int:
    if isinstance(value, bool):
        raise NormalizationError(f"invalid {name}: {value!r}")
    try:
        result = int(value)
    except (TypeError, ValueError) as exc:
        raise NormalizationError(f"invalid {name}: {value!r}") from exc
    if result < 0:
        raise NormalizationError(f"invalid {name}: {value!r}")
    return result


def _stable_value(value: Any) -> str:
    if isinstance(value, str):
        return value
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
