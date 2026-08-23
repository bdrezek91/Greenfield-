"""Deterministic Deribit books, trades, and option ticker normalization."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable
from decimal import Decimal, InvalidOperation
from typing import Any

from src.data.normalized_event import (
    DERIBIT_NORMALIZER_VERSION,
    NORMALIZED_EVENT_SCHEMA_VERSION,
    NormalizationError,
    NormalizationReport,
    NormalizedMarketEvent,
)
from src.data.raw_event import RawMarketEvent


def normalize_deribit_event(event: RawMarketEvent) -> tuple[NormalizedMarketEvent, ...]:
    """Normalize one single-instrument notification without guessing its kind."""
    if event.exchange != "deribit":
        raise NormalizationError(f"expected Deribit event, received {event.exchange!r}")
    if event.channel == "control":
        return ()
    if event.symbol in {"ALL", "MULTI"}:
        raise NormalizationError("Deribit market message must resolve one instrument")
    message = json.loads(event.payload_text, parse_float=Decimal)
    params = message.get("params")
    if not isinstance(params, dict):
        raise NormalizationError("Deribit params must be an object")
    data = params.get("data")
    if event.channel == "orderbook":
        if event.message_type not in {"snapshot", "delta"} or not isinstance(data, dict):
            raise NormalizationError("Deribit book message must be a snapshot/change object")
        records = _book_records(event, data)
    elif event.channel == "trades":
        records = _trade_records(event, data)
    elif event.channel == "ticker":
        if not isinstance(data, dict):
            raise NormalizationError("Deribit ticker data must be an object")
        records = _ticker_records(event, data)
    else:
        raise NormalizationError(f"unsupported Deribit channel: {event.channel!r}")
    return tuple(_build(event, index, **record) for index, record in enumerate(records))


def normalize_deribit_events(
    events: Iterable[RawMarketEvent],
) -> tuple[list[NormalizedMarketEvent], NormalizationReport]:
    ordered = sorted(
        events, key=lambda item: (item.receive_ts_ns, item.receive_sequence, item.event_id)
    )
    rows: list[NormalizedMarketEvent] = []
    channels: dict[str, int] = {}
    records: dict[str, int] = {}
    skipped = 0
    for event in ordered:
        channels[event.channel] = channels.get(event.channel, 0) + 1
        normalized = normalize_deribit_event(event)
        skipped += event.channel == "control"
        for row in normalized:
            rows.append(row)
            records[row.record_type] = records.get(row.record_type, 0) + 1
    digest = hashlib.sha256("\n".join(row.normalized_id for row in rows).encode("ascii"))
    return rows, NormalizationReport(
        raw_event_count=len(ordered),
        normalized_row_count=len(rows),
        skipped_control_count=skipped,
        raw_channel_counts=dict(sorted(channels.items())),
        normalized_record_counts=dict(sorted(records.items())),
        normalized_ids_sha256=digest.hexdigest(),
    )


def _book_records(event: RawMarketEvent, data: dict[str, Any]) -> list[dict[str, Any]]:
    _instrument(event, data.get("instrument_name"))
    timestamp = _positive_int(data.get("timestamp"), "timestamp")
    change_id = _positive_int(data.get("change_id"), "change_id")
    previous = data.get("prev_change_id")
    previous_id = None if previous is None else _positive_int(previous, "prev_change_id")
    output: list[dict[str, Any]] = []
    for side, field in (("bid", "bids"), ("ask", "asks")):
        levels = data.get(field)
        if not isinstance(levels, list):
            raise NormalizationError(f"Deribit {field} must be a list")
        for level in levels:
            if not isinstance(level, list) or len(level) != 3:
                raise NormalizationError(f"invalid Deribit book level: {level!r}")
            action = str(level[0])
            if action not in {"new", "change", "delete"}:
                raise NormalizationError(f"invalid Deribit book action: {action!r}")
            size = _decimal(level[2], positive=False, name="size")
            if action == "delete" and Decimal(size) != 0:
                raise NormalizationError("Deribit delete level must have zero size")
            output.append(
                {
                    "record_type": "book_level",
                    "event_ts_ms": timestamp,
                    "book_side": side,
                    "book_action": "delete" if action == "delete" else "upsert",
                    "price": _decimal(level[1], positive=True, name="price"),
                    "size": size,
                    "first_update_id": change_id,
                    "previous_update_id": previous_id,
                }
            )
    return output


def _trade_records(event: RawMarketEvent, data: Any) -> list[dict[str, Any]]:
    if not isinstance(data, list) or any(not isinstance(item, dict) for item in data):
        raise NormalizationError("Deribit trades must be a list of objects")
    output: list[dict[str, Any]] = []
    for trade in data:
        _instrument(event, trade.get("instrument_name"))
        side = str(trade.get("direction") or "")
        if side not in {"buy", "sell"}:
            raise NormalizationError(f"invalid Deribit trade direction: {side!r}")
        trade_id = str(trade.get("trade_id") or "")
        if not trade_id:
            raise NormalizationError("Deribit trade ID is required")
        trade_sequence = _positive_int(trade.get("trade_seq"), "trade_seq")
        output.append(
            {
                "record_type": "trade",
                "event_ts_ms": _positive_int(trade.get("timestamp"), "timestamp"),
                "side": side,
                "price": _decimal(trade.get("price"), positive=True, name="price"),
                "size": _decimal(trade.get("amount"), positive=True, name="size"),
                "trade_id": trade_id,
                "tick_direction": str(trade.get("tick_direction")),
                "first_update_id": trade_sequence,
            }
        )
    return output


def _ticker_records(event: RawMarketEvent, data: dict[str, Any]) -> list[dict[str, Any]]:
    _instrument(event, data.get("instrument_name"))
    timestamp = _positive_int(data.get("timestamp"), "timestamp")
    output: list[dict[str, Any]] = []
    for name in sorted(data):
        if name in {"instrument_name", "timestamp"}:
            continue
        output.append(
            {
                "record_type": "ticker_metric",
                "event_ts_ms": timestamp,
                "metric_name": name,
                "metric_value": _stable(data[name]),
            }
        )
    return output


def _build(raw: RawMarketEvent, index: int, **values: Any) -> NormalizedMarketEvent:
    identifier = hashlib.sha256(
        f"{DERIBIT_NORMALIZER_VERSION}|{raw.event_id}|{index}".encode("ascii")
    ).hexdigest()
    return NormalizedMarketEvent(
        schema_version=NORMALIZED_EVENT_SCHEMA_VERSION,
        normalizer_version=DERIBIT_NORMALIZER_VERSION,
        normalized_id=identifier,
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
        row_index=index,
        **values,
    )


def _instrument(event: RawMarketEvent, value: Any) -> None:
    if str(value or "") != event.symbol:
        raise NormalizationError(
            f"Deribit instrument mismatch: envelope={event.symbol!r}, data={value!r}"
        )
    topic_instrument = _topic_instrument(event.topic)
    if topic_instrument is not None and topic_instrument != event.symbol:
        raise NormalizationError(
            f"Deribit instrument mismatch: topic={topic_instrument!r}, data={event.symbol!r}"
        )


def _topic_instrument(topic: str) -> str | None:
    parts = topic.split(".")
    if len(parts) < 3 or parts[0] not in {"book", "trades", "ticker"}:
        return None
    if parts[1] in {"future", "option", "spot", "future_combo", "option_combo"}:
        return None
    return parts[1]


def _decimal(value: Any, *, positive: bool, name: str) -> str:
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


def _stable(value: Any) -> str:
    if isinstance(value, str):
        return value
    if isinstance(value, Decimal):
        return format(value, "f")
    return json.dumps(_json_safe(value), sort_keys=True, separators=(",", ":"))


def _json_safe(value: Any) -> Any:
    if isinstance(value, Decimal):
        return format(value, "f")
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_json_safe(item) for item in value]
    return value
