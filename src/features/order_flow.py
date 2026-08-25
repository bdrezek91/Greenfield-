"""Causal ATAS-like trade-flow and L2 features from normalized Silver rows."""

from __future__ import annotations

from decimal import Decimal
from typing import Any

import pandas as pd

from src.data.normalized_event import NormalizedMarketEvent


class OrderFlowError(RuntimeError):
    """Order-flow state is incomplete, out of order, or crosses streams."""


class TradeFlowAccumulator:
    """Chunk-stable aggressor delta and CVD aggregation."""

    def __init__(self, symbol: str, *, bucket_ms: int = 60_000) -> None:
        if bucket_ms <= 0:
            raise ValueError("bucket_ms must be positive")
        self.symbol = symbol
        self.bucket_ms = bucket_ms
        self.cvd = Decimal(0)
        self._bucket: int | None = None
        self._buy = Decimal(0)
        self._sell = Decimal(0)
        self._notional = Decimal(0)
        self._count = 0
        self._max_receive_ns = 0
        self._last_key: tuple[int, int, int, int, str] | None = None

    def update(self, rows: list[NormalizedMarketEvent]) -> list[dict[str, Any]]:
        emitted = []
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
                raise OrderFlowError("trade stream is not strictly ordered")
            self._last_key = key
            bucket = row.event_ts_ms // self.bucket_ms * self.bucket_ms
            if self._bucket is not None and bucket != self._bucket:
                if bucket < self._bucket:
                    raise OrderFlowError("trade bucket regressed")
                emitted.append(self._emit())
            if self._bucket is None:
                self._bucket = bucket
            size = Decimal(row.size or "")
            price = Decimal(row.price or "")
            if row.side == "buy":
                self._buy += size
            else:
                self._sell += size
            self._notional += price * size
            self._count += 1
            self._max_receive_ns = max(self._max_receive_ns, row.receive_ts_ns)
        return emitted

    def finalize(self) -> list[dict[str, Any]]:
        return [] if self._bucket is None else [self._emit()]

    def _emit(self) -> dict[str, Any]:
        assert self._bucket is not None
        delta = self._buy - self._sell
        volume = self._buy + self._sell
        self.cvd += delta
        feature_ns = max(
            (self._bucket + self.bucket_ms) * 1_000_000,
            self._max_receive_ns,
        )
        result = {
            "timestamp": pd.Timestamp(feature_ns, unit="ns", tz="UTC"),
            "max_source_timestamp": pd.Timestamp(self._max_receive_ns, unit="ns", tz="UTC"),
            "buy_volume": float(self._buy),
            "sell_volume": float(self._sell),
            "trade_volume": float(volume),
            "trade_delta": float(delta),
            "cvd": float(self.cvd),
            "trade_count": self._count,
            "trade_vwap": float(self._notional / volume),
        }
        self._bucket = None
        self._buy = Decimal(0)
        self._sell = Decimal(0)
        self._notional = Decimal(0)
        self._count = 0
        self._max_receive_ns = 0
        return result

    def _validate(self, row: NormalizedMarketEvent) -> None:
        if row.record_type != "trade" or row.channel != "trades":
            raise OrderFlowError("TradeFlowAccumulator accepts only trade rows")
        if row.symbol != self.symbol:
            raise OrderFlowError("trade row crossed symbol streams")
        if row.side not in {"buy", "sell"} or row.price is None or row.size is None:
            raise OrderFlowError("trade row is incomplete")


class L2ImbalanceAccumulator:
    """Replay normalized snapshot/delta levels and emit top-depth L2 features."""

    def __init__(self, symbol: str, *, depth_levels: int = 5) -> None:
        if depth_levels <= 0:
            raise ValueError("depth_levels must be positive")
        self.symbol = symbol
        self.depth_levels = depth_levels
        self._bids: dict[Decimal, Decimal] = {}
        self._asks: dict[Decimal, Decimal] = {}
        self._ready = False
        self._update_id: int | None = None
        self._pending: list[NormalizedMarketEvent] = []
        self._pending_raw_id: str | None = None
        self._last_receive_key: tuple[int, int, int, str] | None = None
        self._connection_id: str | None = None

    def update(self, rows: list[NormalizedMarketEvent]) -> list[dict[str, Any]]:
        emitted = []
        for row in rows:
            self._validate_row(row)
            key = (row.receive_ts_ns, row.receive_sequence, row.row_index, row.normalized_id)
            if self._last_receive_key is not None and key <= self._last_receive_key:
                raise OrderFlowError("L2 stream is not strictly ordered")
            self._last_receive_key = key
            if self._pending_raw_id is not None and row.raw_event_id != self._pending_raw_id:
                emitted.append(self._apply_pending())
            if not self._pending:
                self._pending_raw_id = row.raw_event_id
            self._pending.append(row)
        return emitted

    def finalize(self) -> list[dict[str, Any]]:
        return [] if not self._pending else [self._apply_pending()]

    def _apply_pending(self) -> dict[str, Any]:
        rows = self._pending
        message_types = {row.message_type for row in rows}
        update_ids = {row.update_id for row in rows}
        connections = {row.connection_id for row in rows}
        if len(message_types) != 1 or len(update_ids) != 1 or len(connections) != 1:
            raise OrderFlowError("one raw L2 event has inconsistent metadata")
        message_type = next(iter(message_types))
        update_id = next(iter(update_ids))
        connection_id = next(iter(connections))
        if update_id is None:
            raise OrderFlowError("L2 update_id is required")
        if message_type == "snapshot":
            bids: dict[Decimal, Decimal] = {}
            asks: dict[Decimal, Decimal] = {}
            self._connection_id = connection_id
        elif message_type == "delta":
            if not self._ready or self._update_id is None or connection_id != self._connection_id:
                self._invalidate()
                raise OrderFlowError("L2 delta arrived before snapshot")
            if update_id != self._update_id + 1:
                self._invalidate()
                raise OrderFlowError("L2 update gap or regression")
            bids, asks = dict(self._bids), dict(self._asks)
        else:
            raise OrderFlowError(f"invalid L2 message type: {message_type!r}")
        for row in rows:
            side = bids if row.book_side == "bid" else asks
            price, size = Decimal(row.price or ""), Decimal(row.size or "")
            if row.book_action == "delete":
                side.pop(price, None)
            else:
                side[price] = size
        if not bids or not asks or max(bids) >= min(asks):
            self._invalidate()
            raise OrderFlowError("L2 book is empty or crossed")
        self._bids, self._asks = bids, asks
        self._ready, self._update_id = True, update_id
        result = self._features(rows)
        self._pending = []
        self._pending_raw_id = None
        return result

    def _features(self, rows: list[NormalizedMarketEvent]) -> dict[str, Any]:
        bids = sorted(self._bids.items(), reverse=True)[: self.depth_levels]
        asks = sorted(self._asks.items())[: self.depth_levels]
        bid_depth = sum((size for _, size in bids), Decimal(0))
        ask_depth = sum((size for _, size in asks), Decimal(0))
        total = bid_depth + ask_depth
        best_bid, best_ask = bids[0][0], asks[0][0]
        imbalance = (bid_depth - ask_depth) / total
        microprice = (best_ask * bid_depth + best_bid * ask_depth) / total
        max_receive = max(row.receive_ts_ns for row in rows)
        event_ns = max(row.event_ts_ms for row in rows) * 1_000_000
        return {
            "timestamp": pd.Timestamp(max(max_receive, event_ns), unit="ns", tz="UTC"),
            "max_source_timestamp": pd.Timestamp(max_receive, unit="ns", tz="UTC"),
            "best_bid": float(best_bid),
            "best_ask": float(best_ask),
            "spread": float(best_ask - best_bid),
            "mid_price": float((best_bid + best_ask) / 2),
            "microprice": float(microprice),
            "bid_depth": float(bid_depth),
            "ask_depth": float(ask_depth),
            "book_imbalance": float(imbalance),
            "book_update_id": self._update_id,
        }

    def _validate_row(self, row: NormalizedMarketEvent) -> None:
        if row.record_type != "book_level" or row.channel != "orderbook":
            raise OrderFlowError("L2 accumulator accepts only book-level rows")
        if row.symbol != self.symbol:
            raise OrderFlowError("L2 row crossed symbol streams")
        if row.book_side not in {"bid", "ask"} or row.book_action not in {
            "upsert",
            "delete",
        }:
            raise OrderFlowError("L2 row is incomplete")

    def _invalidate(self) -> None:
        self._bids.clear()
        self._asks.clear()
        self._ready = False
        self._update_id = None
        self._pending = []
        self._pending_raw_id = None
        self._connection_id = None


def trade_flow_frame(
    rows: list[NormalizedMarketEvent], *, symbol: str, bucket_ms: int = 60_000
) -> pd.DataFrame:
    accumulator = TradeFlowAccumulator(symbol, bucket_ms=bucket_ms)
    output = accumulator.update(rows) + accumulator.finalize()
    return pd.DataFrame(output)


def l2_imbalance_frame(
    rows: list[NormalizedMarketEvent], *, symbol: str, depth_levels: int = 5
) -> pd.DataFrame:
    accumulator = L2ImbalanceAccumulator(symbol, depth_levels=depth_levels)
    output = accumulator.update(rows) + accumulator.finalize()
    return pd.DataFrame(output)
