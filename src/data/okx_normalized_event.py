"""Deterministic OKX Bronze-to-Silver normalization."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable
from decimal import Decimal, InvalidOperation
from typing import Any

from src.data.normalized_event import (
    NORMALIZED_EVENT_SCHEMA_VERSION,
    OKX_NORMALIZER_VERSION,
    NormalizationError,
    NormalizationReport,
    NormalizedMarketEvent,
)
from src.data.raw_event import RawMarketEvent


def normalize_okx_event(event: RawMarketEvent) -> tuple[NormalizedMarketEvent, ...]:
    """Normalize one immutable OKX event while retaining replay lineage."""
    if event.exchange != "okx":
        raise NormalizationError(f"expected OKX event, received {event.exchange!r}")
    if event.channel == "control":
        return ()
    message = event.payload()
    data = message.get("data")
    if not isinstance(data, list) or any(not isinstance(item, dict) for item in data):
        raise NormalizationError("OKX data must be a list of objects")
    records: list[dict[str, Any]] = []
    if event.channel == "orderbook":
        if event.message_type not in {"snapshot", "delta"}:
            raise NormalizationError(f"invalid OKX book message type: {event.message_type!r}")
        if len(data) != 1:
            raise NormalizationError("OKX book message must contain one data object")
        _validate_instrument(event, data[0])
        records = _book_records(event, data[0])
    elif event.channel == "trades":
        for item in data:
            _validate_instrument(event, item)
        records = [_trade_record(item) for item in data]
    elif event.channel == "ticker":
        for item in data:
            _validate_instrument(event, item)
        records = _ticker_records(data)
    else:
        raise NormalizationError(f"unsupported OKX channel: {event.channel!r}")
    return tuple(_build(event, index, **record) for index, record in enumerate(records))


def normalize_okx_events(
    events: Iterable[RawMarketEvent],
) -> tuple[list[NormalizedMarketEvent], NormalizationReport]:
    ordered = sorted(
        events,
        key=lambda item: (item.receive_ts_ns, item.receive_sequence, item.event_id),
    )
    rows: list[NormalizedMarketEvent] = []
    channels: dict[str, int] = {}
    records: dict[str, int] = {}
    skipped = 0
    for event in ordered:
        channels[event.channel] = channels.get(event.channel, 0) + 1
        normalized = normalize_okx_event(event)
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
    timestamp = _positive_int(data.get("ts"), "timestamp")
    sequence = _non_negative_int(data.get("seqId"), "seqId")
    previous = _integer(data.get("prevSeqId"), "prevSeqId")
    output = []
    for side, field in (("bid", "bids"), ("ask", "asks")):
        levels = data.get(field)
        if not isinstance(levels, list):
            raise NormalizationError(f"OKX {field} must be a list")
        for level in levels:
            if not isinstance(level, list) or len(level) < 2:
                raise NormalizationError(f"invalid OKX book level: {level!r}")
            price = _decimal(level[0], positive=True, name="price")
            size = _decimal(level[1], positive=False, name="size")
            output.append(
                {
                    "record_type": "book_level",
                    "event_ts_ms": timestamp,
                    "book_side": side,
                    "book_action": "delete" if Decimal(size) == 0 else "upsert",
                    "price": price,
                    "size": size,
                    "first_update_id": sequence,
                    "previous_update_id": previous,
                }
            )
    return output


def _trade_record(data: dict[str, Any]) -> dict[str, Any]:
    side = str(data.get("side"))
    if side not in {"buy", "sell"}:
        raise NormalizationError(f"invalid OKX trade side: {side!r}")
    trade_id = str(data.get("tradeId") or "")
    if not trade_id:
        raise NormalizationError("OKX trade ID is required")
    return {
        "record_type": "trade",
        "event_ts_ms": _positive_int(data.get("ts"), "timestamp"),
        "side": side,
        "price": _decimal(data.get("px"), positive=True, name="price"),
        "size": _decimal(data.get("sz"), positive=True, name="size"),
        "trade_id": trade_id,
    }


def _ticker_records(data: list[dict[str, Any]]) -> list[dict[str, Any]]:
    output = []
    for item in data:
        timestamp = _positive_int(item.get("ts"), "timestamp")
        for name in sorted(item):
            if name in {"instId", "ts"}:
                continue
            output.append(
                {
                    "record_type": "ticker_metric",
                    "event_ts_ms": timestamp,
                    "metric_name": name,
                    "metric_value": _stable(item[name]),
                }
            )
    return output


def _build(raw: RawMarketEvent, index: int, **values: Any) -> NormalizedMarketEvent:
    identifier = hashlib.sha256(
        f"{OKX_NORMALIZER_VERSION}|{raw.event_id}|{index}".encode("ascii")
    ).hexdigest()
    return NormalizedMarketEvent(
        schema_version=NORMALIZED_EVENT_SCHEMA_VERSION,
        normalizer_version=OKX_NORMALIZER_VERSION,
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


def _validate_instrument(event: RawMarketEvent, data: dict[str, Any]) -> None:
    instrument = data.get("instId")
    if instrument is not None and str(instrument) != event.symbol:
        raise NormalizationError(
            f"OKX instrument mismatch: envelope={event.symbol!r}, data={instrument!r}"
        )


def _decimal(value: Any, *, positive: bool, name: str) -> str:
    try:
        number = Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise NormalizationError(f"invalid {name}: {value!r}") from exc
    if not number.is_finite() or number < 0 or (positive and number <= 0):
        raise NormalizationError(f"invalid {name}: {value!r}")
    return format(number, "f")


def _integer(value: Any, name: str) -> int:
    if isinstance(value, bool):
        raise NormalizationError(f"invalid {name}: {value!r}")
    try:
        return int(value)
    except (TypeError, ValueError) as exc:
        raise NormalizationError(f"invalid {name}: {value!r}") from exc


def _non_negative_int(value: Any, name: str) -> int:
    result = _integer(value, name)
    if result < 0:
        raise NormalizationError(f"invalid {name}: {value!r}")
    return result


def _positive_int(value: Any, name: str) -> int:
    result = _integer(value, name)
    if result <= 0:
        raise NormalizationError(f"invalid {name}: {value!r}")
    return result


def _stable(value: Any) -> str:
    return (
        value
        if isinstance(value, str)
        else json.dumps(value, sort_keys=True, separators=(",", ":"))
    )
