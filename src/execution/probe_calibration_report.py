"""Fail-closed progress and calibration report for Bybit Demo probes."""

from __future__ import annotations

import math
from pathlib import Path
from typing import Any

from src.data.binance_public_archive import sha256_file
from src.execution.execution_probe_journal import (
    ExecutionProbeJournal,
    ExecutionProbeQuoteRecord,
    ExecutionProbeRecord,
)

SYMBOLS = ("BTCUSDT", "ETHUSDT", "SOLUSDT")
MODES = ("MAKER", "TAKER")


def build_probe_calibration_report(
    journal_path: Path,
    *,
    initial_minimum_per_bucket: int = 30,
    production_minimum_per_bucket: int = 100,
    maximum_quote_age_seconds: float = 5.0,
) -> dict[str, Any]:
    if initial_minimum_per_bucket < 1:
        raise ValueError("initial probe minimum must be positive")
    if production_minimum_per_bucket < initial_minimum_per_bucket:
        raise ValueError("production probe minimum cannot be below initial minimum")
    journal = ExecutionProbeJournal(journal_path)
    records = journal.load_probe_records()
    quote_records = journal.load_quote_records()
    buckets = [
        _bucket(
            symbol=symbol,
            mode=mode,
            records=tuple(
                record
                for record in records
                if record.observation.symbol == symbol and record.probe_mode == mode
            ),
            quote_records=quote_records,
            maximum_quote_age_seconds=maximum_quote_age_seconds,
            initial_minimum=initial_minimum_per_bucket,
            production_minimum=production_minimum_per_bucket,
        )
        for symbol in SYMBOLS
        for mode in MODES
    ]
    initial_ready = all(item["initial_ready"] for item in buckets)
    production_ready = all(item["production_ready"] for item in buckets)
    return {
        "schema_version": 1,
        "status": "CALIBRATION_READY" if production_ready else "COLLECTING",
        "journal_sha256": sha256_file(journal_path),
        "observation_count": len(records),
        "quote_count": len(quote_records),
        "initial_minimum_per_symbol_mode": initial_minimum_per_bucket,
        "production_minimum_per_symbol_mode": production_minimum_per_bucket,
        "initial_ready": initial_ready,
        "production_ready": production_ready,
        "buckets": buckets,
        "promotion_allowed": False,
        "execution_allowed": False,
    }


def _bucket(
    *,
    symbol: str,
    mode: str,
    records: tuple[ExecutionProbeRecord, ...],
    quote_records: tuple[ExecutionProbeQuoteRecord, ...],
    maximum_quote_age_seconds: float,
    initial_minimum: int,
    production_minimum: int,
) -> dict[str, Any]:
    observations = [record.observation for record in records]
    filled = [item for item in observations if not item.rejected]
    rejected = len(observations) - len(filled)
    partial = sum(item.filled_quantity < item.requested_quantity for item in filled)
    quotes_by_trade = {
        record.probe_trade_id: {
            quote.horizon_label: quote.quote
            for quote in quote_records
            if quote.probe_trade_id == record.probe_trade_id
        }
        for record in records
    }
    valid_reference: list[tuple[ExecutionProbeRecord, Any]] = []
    join_issue_count = 0
    for record in records:
        reference = quotes_by_trade.get(record.probe_trade_id, {}).get("REFERENCE")
        age = None if reference is None else (
            record.observation.decision_timestamp_utc - reference.timestamp_utc
        ).total_seconds()
        if reference is None or age is None or not 0 <= age <= maximum_quote_age_seconds:
            join_issue_count += 1
        elif not record.observation.rejected:
            valid_reference.append((record, reference))
    latency = [
        (item.resolved_at_utc - item.submitted_at_utc).total_seconds() for item in filled
    ]
    fee_bps = [
        item.fee_cost_quote / (item.filled_price * item.filled_quantity) * 10_000
        for item in filled
    ]
    spread_bps = [_spread(reference) for _, reference in valid_reference]
    slippage_bps = [
        _slippage(record.observation, reference) for record, reference in valid_reference
    ]
    markout_rows = _markouts(records, quotes_by_trade)
    count = len(observations)
    return {
        "symbol": symbol,
        "mode": mode,
        "observation_count": count,
        "filled_count": len(filled),
        "missed_or_rejected_count": rejected,
        "partial_fill_count": partial,
        "join_issue_count": join_issue_count,
        "fill_probability": len(filled) / count if count else None,
        "partial_fill_probability_given_fill": partial / len(filled) if filled else None,
        "latency_seconds_p50": _quantile(latency, 0.50),
        "latency_seconds_p95": _quantile(latency, 0.95),
        "fee_bps_p50": _quantile(fee_bps, 0.50),
        "fee_bps_p95": _quantile(fee_bps, 0.95),
        "spread_bps_p50": _quantile(spread_bps, 0.50),
        "spread_bps_p95": _quantile(spread_bps, 0.95),
        "slippage_bps_p50": _quantile(slippage_bps, 0.50),
        "slippage_bps_p95": _quantile(slippage_bps, 0.95),
        "markouts": markout_rows,
        "initial_ready": count >= initial_minimum,
        "production_ready": count >= production_minimum,
    }


def _spread(quote: Any) -> float:
    midpoint = (quote.bid_price + quote.ask_price) / 2
    return (quote.ask_price - quote.bid_price) / midpoint * 10_000


def _slippage(order: Any, quote: Any) -> float:
    touch = quote.ask_price if order.side.value == "BUY" else quote.bid_price
    adverse = (
        order.filled_price - touch
        if order.side.value == "BUY"
        else touch - order.filled_price
    )
    return adverse / touch * 10_000


def _markouts(
    records: tuple[ExecutionProbeRecord, ...],
    quotes_by_trade: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    values: dict[float, list[float]] = {}
    for record in records:
        order = record.observation
        if order.rejected:
            continue
        for label, quote in quotes_by_trade.get(record.probe_trade_id, {}).items():
            if not label.startswith("T+") or not label.endswith("s"):
                continue
            horizon = float(label[2:-1])
            mid = (quote.bid_price + quote.ask_price) / 2
            move = mid - order.filled_price
            signed = move if order.side.value == "BUY" else -move
            values.setdefault(horizon, []).append(signed / order.filled_price * 10_000)
    return [
        {
            "horizon_seconds": horizon,
            "sample_count": len(samples),
            "mean_bps": sum(samples) / len(samples),
            "median_bps": _quantile(samples, 0.50),
            "adverse_selection_probability": sum(value < 0 for value in samples)
            / len(samples),
        }
        for horizon, samples in sorted(values.items())
    ]


def _quantile(values: list[float], probability: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    position = (len(ordered) - 1) * probability
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return ordered[lower]
    weight = position - lower
    return ordered[lower] * (1 - weight) + ordered[upper] * weight
