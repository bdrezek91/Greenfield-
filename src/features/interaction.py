"""Causal liquidity interaction: cancellation, replenishment, sweeps, and stalls."""

from __future__ import annotations

from decimal import Decimal
from typing import Any

import pandas as pd

from src.data.normalized_event import NormalizedMarketEvent
from src.features.order_flow import OrderFlowError


class TradeInteractionAccumulator:
    """Chunk-stable sweep, absorption, and exhaustion aggregation."""

    def __init__(
        self,
        symbol: str,
        *,
        bucket_ms: int,
        price_tick: str,
        min_sweep_levels: int = 2,
    ) -> None:
        self.symbol = symbol
        self.bucket_ms = bucket_ms
        self.tick = Decimal(price_tick)
        self.min_sweep_levels = min_sweep_levels
        if bucket_ms <= 0 or self.tick <= 0 or min_sweep_levels < 2:
            raise ValueError("invalid interaction configuration")
        self._bucket: int | None = None
        self._rows: list[NormalizedMarketEvent] = []
        self._previous: dict[str, Decimal] | None = None
        self._last_key: tuple[int, int, int, int, str] | None = None

    def update(self, rows: list[NormalizedMarketEvent]) -> list[dict[str, object]]:
        output = []
        for row in rows:
            self._validate(row)
            key = (
                row.event_ts_ms,
                row.receive_ts_ns,
                row.receive_sequence,
                row.row_index,
                row.normalized_id,
            )
            if self._last_key is not None and key <= self._last_key:
                raise OrderFlowError("interaction trade stream is not strictly ordered")
            self._last_key = key
            bucket = row.event_ts_ms // self.bucket_ms * self.bucket_ms
            if self._bucket is not None and bucket != self._bucket:
                if bucket < self._bucket:
                    raise OrderFlowError("interaction trade bucket regressed")
                output.append(self._emit())
            if self._bucket is None:
                self._bucket = bucket
            self._rows.append(row)
        return output

    def finalize(self) -> list[dict[str, object]]:
        return [] if self._bucket is None else [self._emit()]

    def _emit(self) -> dict[str, object]:
        assert self._bucket is not None and self._rows
        group = self._rows
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
        buy_sweep = _monotonic_sweep(buy_prices, increasing=True, minimum=self.min_sweep_levels)
        sell_sweep = _monotonic_sweep(sell_prices, increasing=False, minimum=self.min_sweep_levels)
        open_price, close_price = prices[0], prices[-1]
        high, low = max(prices), min(prices)
        progress = (close_price - open_price) / self.tick
        buy_exhaustion = bool(
            self._previous and high > self._previous["high"] and buy < self._previous["buy"]
        )
        sell_exhaustion = bool(
            self._previous and low < self._previous["low"] and sell < self._previous["sell"]
        )
        max_receive = max(row.receive_ts_ns for row in group)
        result: dict[str, object] = {
            "timestamp": pd.Timestamp(
                max((self._bucket + self.bucket_ms) * 1_000_000, max_receive),
                unit="ns",
                tz="UTC",
            ),
            "max_source_timestamp": pd.Timestamp(max_receive, unit="ns", tz="UTC"),
            "buy_sweep": int(buy_sweep),
            "sell_sweep": int(sell_sweep),
            "buy_sweep_levels": len(set(buy_prices)) if buy_sweep else 0,
            "sell_sweep_levels": len(set(sell_prices)) if sell_sweep else 0,
            "buy_absorption": int(buy > sell and progress <= 0),
            "sell_absorption": int(sell > buy and progress >= 0),
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
        self._previous = {"high": high, "low": low, "buy": buy, "sell": sell}
        self._bucket = None
        self._rows = []
        return result

    def _validate(self, row: NormalizedMarketEvent) -> None:
        if row.record_type != "trade" or row.channel != "trades" or row.symbol != self.symbol:
            raise OrderFlowError("interaction features crossed normalized trade streams")
        if row.side not in {"buy", "sell"} or row.price is None or row.size is None:
            raise OrderFlowError("interaction trade row is incomplete")


class BookLiquidityAccumulator:
    """Chunk-stable, connection-scoped L2 additions/cancellations/refills."""

    def __init__(self, symbol: str, *, replenishment_window_updates: int = 5) -> None:
        if replenishment_window_updates <= 0:
            raise ValueError("replenishment_window_updates must be positive")
        self.symbol = symbol
        self.replenishment_window_updates = replenishment_window_updates
        self._bids: dict[Decimal, Decimal] = {}
        self._asks: dict[Decimal, Decimal] = {}
        self._last_reduction: dict[tuple[str, Decimal], int] = {}
        self._previous_update_id: int | None = None
        self._connection_id: str | None = None
        self._update_counter = 0
        self._pending: list[NormalizedMarketEvent] = []
        self._pending_raw_id: str | None = None
        self._last_key: tuple[int, int, int, str] | None = None

    def update(self, rows: list[NormalizedMarketEvent]) -> list[dict[str, object]]:
        output = []
        for row in rows:
            self._validate(row)
            key = (row.receive_ts_ns, row.receive_sequence, row.row_index, row.normalized_id)
            if self._last_key is not None and key <= self._last_key:
                raise OrderFlowError("liquidity L2 stream is not strictly ordered")
            self._last_key = key
            if self._pending_raw_id is not None and row.raw_event_id != self._pending_raw_id:
                output.append(self._apply_pending())
            if not self._pending:
                self._pending_raw_id = row.raw_event_id
            self._pending.append(row)
        return output

    def finalize(self) -> list[dict[str, object]]:
        return [] if not self._pending else [self._apply_pending()]

    def _apply_pending(self) -> dict[str, object]:
        group = self._pending
        message_type = _one({row.message_type for row in group}, "message type")
        update_id = _one({row.update_id for row in group}, "update_id")
        connection_id = _one({row.connection_id for row in group}, "connection_id")
        if not isinstance(update_id, int):
            raise OrderFlowError("L2 update_id is required")
        self._update_counter += 1
        metrics = {name: Decimal(0) for name in _LIQUIDITY_METRICS}
        if message_type == "snapshot":
            self._bids, self._asks = {}, {}
            self._last_reduction = {}
            self._previous_update_id = update_id
            self._connection_id = str(connection_id)
            for row in group:
                target = self._bids if row.book_side == "bid" else self._asks
                size = Decimal(row.size or "")
                if size > 0:
                    target[Decimal(row.price or "")] = size
        elif message_type == "delta":
            if (
                self._previous_update_id is None
                or connection_id != self._connection_id
                or update_id != self._previous_update_id + 1
            ):
                self._invalidate()
                raise OrderFlowError("L2 update gap, regression, or delta before snapshot")
            self._previous_update_id = update_id
            for row in group:
                side_name = str(row.book_side)
                target = self._bids if side_name == "bid" else self._asks
                price = Decimal(row.price or "")
                old = target.get(price, Decimal(0))
                new = Decimal(row.size or "")
                change = new - old
                if change > 0:
                    metrics[f"{side_name}_added"] += change
                    reduced_at = self._last_reduction.get((side_name, price))
                    if (
                        reduced_at is not None
                        and self._update_counter - reduced_at <= self.replenishment_window_updates
                    ):
                        metrics[f"{side_name}_replenished"] += change
                elif change < 0:
                    metrics[f"{side_name}_cancelled"] += -change
                    self._last_reduction[(side_name, price)] = self._update_counter
                if new == 0:
                    target.pop(price, None)
                else:
                    target[price] = new
        else:
            raise OrderFlowError(f"invalid L2 message type: {message_type!r}")
        if not self._bids or not self._asks or max(self._bids) >= min(self._asks):
            self._invalidate()
            raise OrderFlowError("L2 book is empty or crossed")
        max_receive = max(row.receive_ts_ns for row in group)
        event_ns = max(row.event_ts_ms for row in group) * 1_000_000
        result: dict[str, object] = {
            "timestamp": pd.Timestamp(max(max_receive, event_ns), unit="ns", tz="UTC"),
            "max_source_timestamp": pd.Timestamp(max_receive, unit="ns", tz="UTC"),
            **{name: float(value) for name, value in metrics.items()},
            "book_update_id": update_id,
        }
        self._pending = []
        self._pending_raw_id = None
        return result

    def _validate(self, row: NormalizedMarketEvent) -> None:
        if row.record_type != "book_level" or row.channel != "orderbook":
            raise OrderFlowError("BookLiquidityAccumulator accepts only L2 rows")
        if row.symbol != self.symbol or row.book_side not in {"bid", "ask"}:
            raise OrderFlowError("liquidity features crossed normalized streams")
        if row.book_action not in {"upsert", "delete"} or row.price is None or row.size is None:
            raise OrderFlowError("liquidity L2 row is incomplete")

    def _invalidate(self) -> None:
        self._bids.clear()
        self._asks.clear()
        self._last_reduction.clear()
        self._previous_update_id = None
        self._connection_id = None
        self._pending = []
        self._pending_raw_id = None


def book_liquidity_change_frame(
    rows: list[NormalizedMarketEvent],
    *,
    symbol: str,
    replenishment_window_updates: int = 5,
) -> pd.DataFrame:
    """Replay L2 and measure actual size additions, cancellations, and refills."""
    accumulator = BookLiquidityAccumulator(
        symbol, replenishment_window_updates=replenishment_window_updates
    )
    return pd.DataFrame(accumulator.update(rows) + accumulator.finalize())


def trade_interaction_frame(
    rows: list[NormalizedMarketEvent],
    *,
    symbol: str,
    bucket_ms: int,
    price_tick: str,
    min_sweep_levels: int = 2,
) -> pd.DataFrame:
    """Detect tape sweeps, absorption stalls, and weakening new extremes."""
    ordered = sorted(
        rows,
        key=lambda row: (
            row.event_ts_ms,
            row.receive_ts_ns,
            row.receive_sequence,
            row.row_index,
        ),
    )
    accumulator = TradeInteractionAccumulator(
        symbol,
        bucket_ms=bucket_ms,
        price_tick=price_tick,
        min_sweep_levels=min_sweep_levels,
    )
    return pd.DataFrame(accumulator.update(ordered) + accumulator.finalize())


_LIQUIDITY_METRICS = (
    "bid_added",
    "ask_added",
    "bid_cancelled",
    "ask_cancelled",
    "bid_replenished",
    "ask_replenished",
)


def _one(values: set[Any], name: str) -> Any:
    if len(values) != 1:
        raise OrderFlowError(f"inconsistent {name} in raw event")
    return next(iter(values))


def _monotonic_sweep(prices: list[Decimal], *, increasing: bool, minimum: int) -> bool:
    if len(set(prices)) < minimum:
        return False
    pairs = zip(prices, prices[1:], strict=False)
    return all(right >= left if increasing else right <= left for left, right in pairs)
