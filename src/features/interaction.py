"""Causal liquidity interaction: cancellation, replenishment, sweeps, and stalls."""

from __future__ import annotations

from decimal import Decimal
from typing import Any

import pandas as pd

from src.data.normalized_event import NormalizedMarketEvent
from src.features.order_flow import OrderFlowError


def book_liquidity_change_frame(
    rows: list[NormalizedMarketEvent],
    *,
    symbol: str,
    replenishment_window_updates: int = 5,
) -> pd.DataFrame:
    """Replay L2 and measure actual size additions, cancellations, and refills."""
    if replenishment_window_updates <= 0:
        raise ValueError("replenishment_window_updates must be positive")
    groups = _raw_event_groups(rows, record_type="book_level", symbol=symbol)
    bids: dict[Decimal, Decimal] = {}
    asks: dict[Decimal, Decimal] = {}
    last_reduction: dict[tuple[str, Decimal], int] = {}
    previous_update_id: int | None = None
    output = []
    update_counter = 0
    for group in groups:
        update_counter += 1
        message_type = _one({row.message_type for row in group}, "message type")
        update_id = _one({row.update_id for row in group}, "update_id")
        if not isinstance(update_id, int):
            raise OrderFlowError("L2 update_id is required")
        if message_type == "snapshot":
            bids, asks = {}, {}
            previous_update_id = update_id
            for row in group:
                target = bids if row.book_side == "bid" else asks
                target[Decimal(row.price or "")] = Decimal(row.size or "")
            metrics = {name: Decimal(0) for name in _LIQUIDITY_METRICS}
        elif message_type == "delta":
            if previous_update_id is None or update_id != previous_update_id + 1:
                raise OrderFlowError("L2 update gap, regression, or delta before snapshot")
            previous_update_id = update_id
            metrics = {name: Decimal(0) for name in _LIQUIDITY_METRICS}
            for row in group:
                side_name = str(row.book_side)
                target = bids if side_name == "bid" else asks
                price = Decimal(row.price or "")
                old = target.get(price, Decimal(0))
                new = Decimal(row.size or "")
                change = new - old
                if change > 0:
                    metrics[f"{side_name}_added"] += change
                    reduction_at = last_reduction.get((side_name, price))
                    if (
                        reduction_at is not None
                        and update_counter - reduction_at <= replenishment_window_updates
                    ):
                        metrics[f"{side_name}_replenished"] += change
                elif change < 0:
                    metrics[f"{side_name}_cancelled"] += -change
                    last_reduction[(side_name, price)] = update_counter
                if new == 0:
                    target.pop(price, None)
                else:
                    target[price] = new
        else:
            raise OrderFlowError(f"invalid L2 message type: {message_type!r}")
        if not bids or not asks or max(bids) >= min(asks):
            raise OrderFlowError("L2 book is empty or crossed")
        max_receive = max(row.receive_ts_ns for row in group)
        event_ns = max(row.event_ts_ms for row in group) * 1_000_000
        output.append(
            {
                "timestamp": pd.Timestamp(max(max_receive, event_ns), unit="ns", tz="UTC"),
                "max_source_timestamp": pd.Timestamp(max_receive, unit="ns", tz="UTC"),
                **{name: float(value) for name, value in metrics.items()},
                "book_update_id": update_id,
            }
        )
    return pd.DataFrame(output)


def trade_interaction_frame(
    rows: list[NormalizedMarketEvent],
    *,
    symbol: str,
    bucket_ms: int,
    price_tick: str,
    min_sweep_levels: int = 2,
) -> pd.DataFrame:
    """Detect tape sweeps, absorption stalls, and weakening new extremes."""
    tick = Decimal(price_tick)
    if bucket_ms <= 0 or tick <= 0 or min_sweep_levels < 2:
        raise ValueError("invalid interaction configuration")
    ordered = sorted(
        rows,
        key=lambda row: (
            row.event_ts_ms,
            row.receive_ts_ns,
            row.receive_sequence,
            row.row_index,
        ),
    )
    for row in ordered:
        if row.record_type != "trade" or row.symbol != symbol:
            raise OrderFlowError("interaction features accept one normalized trade stream")
    buckets: dict[int, list[NormalizedMarketEvent]] = {}
    for row in ordered:
        buckets.setdefault(row.event_ts_ms // bucket_ms * bucket_ms, []).append(row)
    output = []
    previous: dict[str, Decimal] | None = None
    for bucket, group in sorted(buckets.items()):
        prices = [Decimal(row.price or "") for row in group]
        sizes = [Decimal(row.size or "") for row in group]
        buy = sum(
            (size for row, size in zip(group, sizes, strict=True) if row.side == "buy"),
            Decimal(0),
        )
        sell = sum(
            (size for row, size in zip(group, sizes, strict=True) if row.side == "sell"),
            Decimal(0),
        )
        buy_prices = [price for row, price in zip(group, prices, strict=True) if row.side == "buy"]
        sell_prices = [
            price for row, price in zip(group, prices, strict=True) if row.side == "sell"
        ]
        buy_sweep = _monotonic_sweep(buy_prices, increasing=True, minimum=min_sweep_levels)
        sell_sweep = _monotonic_sweep(sell_prices, increasing=False, minimum=min_sweep_levels)
        open_price, close_price = prices[0], prices[-1]
        high, low = max(prices), min(prices)
        progress = (close_price - open_price) / tick
        buy_absorption = buy > sell and progress <= 0
        sell_absorption = sell > buy and progress >= 0
        buy_exhaustion = bool(previous and high > previous["high"] and buy < previous["buy"])
        sell_exhaustion = bool(previous and low < previous["low"] and sell < previous["sell"])
        max_receive = max(row.receive_ts_ns for row in group)
        output.append(
            {
                "timestamp": pd.Timestamp(
                    max((bucket + bucket_ms) * 1_000_000, max_receive), unit="ns", tz="UTC"
                ),
                "max_source_timestamp": pd.Timestamp(max_receive, unit="ns", tz="UTC"),
                "buy_sweep": int(buy_sweep),
                "sell_sweep": int(sell_sweep),
                "buy_sweep_levels": len(set(buy_prices)) if buy_sweep else 0,
                "sell_sweep_levels": len(set(sell_prices)) if sell_sweep else 0,
                "buy_absorption": int(buy_absorption),
                "sell_absorption": int(sell_absorption),
                "buy_absorption_score": float(
                    buy / (buy + sell) / (Decimal(1) + max(progress, Decimal(0)))
                ),
                "sell_absorption_score": float(
                    sell / (buy + sell) / (Decimal(1) + max(-progress, Decimal(0)))
                ),
                "buy_exhaustion": int(buy_exhaustion),
                "sell_exhaustion": int(sell_exhaustion),
                "price_progress_ticks": float(progress),
            }
        )
        previous = {"high": high, "low": low, "buy": buy, "sell": sell}
    return pd.DataFrame(output)


_LIQUIDITY_METRICS = (
    "bid_added",
    "ask_added",
    "bid_cancelled",
    "ask_cancelled",
    "bid_replenished",
    "ask_replenished",
)


def _raw_event_groups(
    rows: list[NormalizedMarketEvent], *, record_type: str, symbol: str
) -> list[list[NormalizedMarketEvent]]:
    groups = []
    current = []
    current_id = None
    for row in rows:
        if row.record_type != record_type or row.symbol != symbol:
            raise OrderFlowError("liquidity features crossed normalized streams")
        if current_id is not None and row.raw_event_id != current_id:
            groups.append(current)
            current = []
        current_id = row.raw_event_id
        current.append(row)
    if current:
        groups.append(current)
    return groups


def _one(values: set[Any], name: str) -> Any:
    if len(values) != 1:
        raise OrderFlowError(f"inconsistent {name} in raw event")
    return next(iter(values))


def _monotonic_sweep(prices: list[Decimal], *, increasing: bool, minimum: int) -> bool:
    if len(set(prices)) < minimum:
        return False
    pairs = zip(prices, prices[1:], strict=False)
    return all(right >= left if increasing else right <= left for left, right in pairs)
