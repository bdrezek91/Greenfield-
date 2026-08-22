"""Deterministic Coinbase Advanced Trade Bronze-to-Silver normalization."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable
from datetime import datetime
from decimal import Decimal, InvalidOperation
from typing import Any

from src.data.normalized_event import (
    COINBASE_NORMALIZER_VERSION,
    NORMALIZED_EVENT_SCHEMA_VERSION,
    NormalizationError,
    NormalizationReport,
    NormalizedMarketEvent,
)
from src.data.raw_event import RawMarketEvent


def normalize_coinbase_event(event: RawMarketEvent) -> tuple[NormalizedMarketEvent, ...]:
    """Normalize one single-product message while retaining raw lineage."""
    if event.exchange != "coinbase":
        raise NormalizationError(f"expected Coinbase event, received {event.exchange!r}")
    if event.channel == "control":
        return ()
    if event.symbol in {"ALL", "MULTI"}:
        raise NormalizationError("Coinbase market message must resolve one product")
    message = event.payload()
    events = message.get("events")
    if not isinstance(events, list) or any(not isinstance(item, dict) for item in events):
        raise NormalizationError("Coinbase events must be a list of objects")
    records: list[dict[str, Any]] = []
    if event.channel == "orderbook":
        if event.message_type not in {"snapshot", "delta"}:
            raise NormalizationError(f"invalid Coinbase L2 type: {event.message_type!r}")
        records = _book_records(event, events)
    elif event.channel == "trades":
        records = _trade_records(event, events)
    elif event.channel == "ticker":
        records = _ticker_records(event, events)
    else:
        raise NormalizationError(f"unsupported Coinbase channel: {event.channel!r}")
    return tuple(_build(event, index, **record) for index, record in enumerate(records))


def normalize_coinbase_events(
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
        normalized = normalize_coinbase_event(event)
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


def _book_records(event: RawMarketEvent, events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    for entry in events:
        _product(event, entry.get("product_id"))
        updates = entry.get("updates")
        if not isinstance(updates, list) or any(not isinstance(item, dict) for item in updates):
            raise NormalizationError("Coinbase L2 updates must be a list of objects")
        for update in updates:
            side = str(update.get("side") or "").lower()
            if side not in {"bid", "offer"}:
                raise NormalizationError(f"invalid Coinbase book side: {side!r}")
            size = _decimal(update.get("new_quantity"), positive=False, name="size")
            output.append(
                {
                    "record_type": "book_level",
                    "event_ts_ms": _event_time_ms(update.get("event_time"), event),
                    "book_side": "ask" if side == "offer" else "bid",
                    "book_action": "delete" if Decimal(size) == 0 else "upsert",
                    "price": _decimal(update.get("price_level"), positive=True, name="price"),
                    "size": size,
                    "first_update_id": event.sequence,
                }
            )
    return output


def _trade_records(event: RawMarketEvent, events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    for entry in events:
        trades = entry.get("trades")
        if not isinstance(trades, list) or any(not isinstance(item, dict) for item in trades):
            raise NormalizationError("Coinbase trades must be a list of objects")
        for trade in trades:
            _product(event, trade.get("product_id"))
            maker_side = str(trade.get("side") or "").upper()
            if maker_side not in {"BUY", "SELL"}:
                raise NormalizationError(f"invalid Coinbase maker side: {maker_side!r}")
            trade_id = str(trade.get("trade_id") or "")
            if not trade_id:
                raise NormalizationError("Coinbase trade ID is required")
            output.append(
                {
                    "record_type": "trade",
                    "event_ts_ms": _timestamp_ms(trade.get("time"), "trade time"),
                    "side": "sell" if maker_side == "BUY" else "buy",
                    "price": _decimal(trade.get("price"), positive=True, name="price"),
                    "size": _decimal(trade.get("size"), positive=True, name="size"),
                    "trade_id": trade_id,
                }
            )
    return output


def _ticker_records(event: RawMarketEvent, events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if event.exchange_ts_ms is None:
        raise NormalizationError("Coinbase ticker timestamp is missing")
    output: list[dict[str, Any]] = []
    for entry in events:
        tickers = entry.get("tickers")
        if not isinstance(tickers, list) or any(not isinstance(item, dict) for item in tickers):
            raise NormalizationError("Coinbase tickers must be a list of objects")
        for ticker in tickers:
            _product(event, ticker.get("product_id"))
            for name in sorted(ticker):
                if name == "product_id":
                    continue
                output.append(
                    {
                        "record_type": "ticker_metric",
                        "event_ts_ms": event.exchange_ts_ms,
                        "metric_name": name,
                        "metric_value": _stable(ticker[name]),
                    }
                )
    return output


def _build(raw: RawMarketEvent, index: int, **values: Any) -> NormalizedMarketEvent:
    identifier = hashlib.sha256(
        f"{COINBASE_NORMALIZER_VERSION}|{raw.event_id}|{index}".encode("ascii")
    ).hexdigest()
    return NormalizedMarketEvent(
        schema_version=NORMALIZED_EVENT_SCHEMA_VERSION,
        normalizer_version=COINBASE_NORMALIZER_VERSION,
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


def _product(event: RawMarketEvent, value: Any) -> None:
    if str(value or "") != event.symbol:
        raise NormalizationError(
            f"Coinbase product mismatch: envelope={event.symbol!r}, data={value!r}"
        )


def _event_time_ms(value: Any, event: RawMarketEvent) -> int:
    result = _timestamp_ms(value, "L2 event time")
    if result > 0:
        return result
    if event.exchange_ts_ms is None:
        raise NormalizationError("Coinbase snapshot timestamp is missing")
    return event.exchange_ts_ms


def _timestamp_ms(value: Any, name: str) -> int:
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError as exc:
        raise NormalizationError(f"invalid {name}: {value!r}") from exc
    if parsed.tzinfo is None:
        raise NormalizationError(f"{name} must be timezone-aware")
    return int(parsed.timestamp() * 1000)


def _decimal(value: Any, *, positive: bool, name: str) -> str:
    try:
        number = Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise NormalizationError(f"invalid {name}: {value!r}") from exc
    if not number.is_finite() or number < 0 or (positive and number <= 0):
        raise NormalizationError(f"invalid {name}: {value!r}")
    return format(number, "f")


def _stable(value: Any) -> str:
    return (
        value
        if isinstance(value, str)
        else json.dumps(value, sort_keys=True, separators=(",", ":"))
    )
