"""Deterministic Binance L2 order-book replay from immutable raw events.

Structurally mirrors src/data/bybit_replay.py, adapted to Binance's
protocol differences:

- Sequence continuity reuses `BinanceDepthSequenceGate`
  (src/data/binance_adapter.py) directly rather than reimplementing the
  `U`/`u`/`pu` contract - it is already the tested source of truth for
  what a valid Binance depth chain looks like, used by the live collector
  too. A `message_type == "snapshot"` event (Cycle 19's
  `synthesize_binance_depth_snapshot_event`) bootstraps both the gate and
  the book's actual price levels; without it, replay has no baseline and
  raises `BinanceSnapshotRequired` on the first delta, exactly like the
  live collector does. Raw Bronze data collected before Cycle 19 has no
  snapshot event and therefore cannot be replayed into real price levels
  - only newer data can.
- Only the `orderbook` channel is reconstructed. Binance's `ticker`
  channel (markPrice/24hrTicker/bookTicker) is a series of independent
  full-state pushes with no delta/sequence contract to replay - unlike
  Bybit's ticker channel (snapshot+delta+`cs` cross-sequence), there is
  nothing for a replay tool to verify or reconstruct there, so it is
  deliberately out of scope (still counted in `channel_counts`).
- Per Binance's own documented procedure (already implemented in
  `BinanceDepthSequenceGate.apply`), an event at or before the bootstrap
  snapshot's `lastUpdateId` is silently dropped, not treated as an error
  - this replay tool preserves that exact behavior rather than treating
  every non-increasing update as a hard failure the way Bybit's protocol
  does.
- Like `bybit_replay.py`, a genuine gap/regression raises immediately and
  fails the whole replay (fail-closed) rather than being caught and
  reported as a softer "partial" result - an operator sees exactly where
  continuity broke.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable
from dataclasses import asdict, dataclass
from decimal import Decimal, InvalidOperation
from typing import Any

from src.data.binance_adapter import (
    BinanceDepthSequenceGate,
    BinanceReplayError,
    BinanceSequenceGap,
    BinanceSnapshotRequired,
)
from src.data.raw_event import RawMarketEvent

__all__ = [
    "BinanceDepthSequenceGate",
    "BinanceOrderBook",
    "BinanceReplayError",
    "BinanceReplaySession",
    "BinanceSequenceGap",
    "BinanceSnapshotRequired",
    "InvalidOrderBook",
    "ReplayReport",
    "ReplayedBook",
    "replay_binance",
    "replay_binance_stream",
]


class InvalidOrderBook(BinanceReplayError):
    pass


@dataclass(frozen=True, slots=True)
class ReplayedBook:
    symbol: str
    update_id: int
    bid_levels: int
    ask_levels: int
    best_bid: str
    best_ask: str
    checksum: str


@dataclass(frozen=True, slots=True)
class ReplayReport:
    raw_event_count: int
    channel_counts: dict[str, int]
    orderbooks: dict[str, ReplayedBook]
    replay_checksum: str

    def to_dict(self) -> dict[str, Any]:
        value = asdict(self)
        value["orderbooks"] = {
            symbol: asdict(book) for symbol, book in sorted(self.orderbooks.items())
        }
        return value


class BinanceOrderBook:
    """Exact decimal L2 state, bootstrapped from a persisted REST snapshot
    event and advanced by delta events already accepted by a
    `BinanceDepthSequenceGate`.
    """

    def __init__(self, symbol: str) -> None:
        self.symbol = symbol
        self._bids: dict[Decimal, Decimal] = {}
        self._asks: dict[Decimal, Decimal] = {}
        self.update_id: int | None = None

    @property
    def is_ready(self) -> bool:
        return bool(self._bids) and bool(self._asks) and self.update_id is not None

    def load_snapshot(self, bids: Any, asks: Any, update_id: int) -> None:
        next_bids = {price: size for price, size in _levels(bids, "bids") if size > 0}
        next_asks = {price: size for price, size in _levels(asks, "asks") if size > 0}
        _validate_book(self.symbol, next_bids, next_asks)
        self._bids = next_bids
        self._asks = next_asks
        self.update_id = update_id

    def apply_delta(self, bids: Any, asks: Any, update_id: int) -> None:
        if not self.is_ready:
            raise BinanceSnapshotRequired(f"{self.symbol} delta arrived before a valid snapshot")
        next_bids = dict(self._bids)
        next_asks = dict(self._asks)
        _apply_levels(next_bids, _levels(bids, "b"))
        _apply_levels(next_asks, _levels(asks, "a"))
        _validate_book(self.symbol, next_bids, next_asks)
        self._bids = next_bids
        self._asks = next_asks
        self.update_id = update_id

    def snapshot(self) -> ReplayedBook:
        if not self.is_ready or self.update_id is None:
            raise BinanceSnapshotRequired(f"{self.symbol} has no valid snapshot")
        bids = sorted(self._bids.items(), reverse=True)
        asks = sorted(self._asks.items())
        checksum = _book_checksum(self.symbol, self.update_id, bids, asks)
        return ReplayedBook(
            symbol=self.symbol,
            update_id=self.update_id,
            bid_levels=len(bids),
            ask_levels=len(asks),
            best_bid=_decimal_text(bids[0][0]),
            best_ask=_decimal_text(asks[0][0]),
            checksum=checksum,
        )


class BinanceReplaySession:
    """Incremental replay suitable for multi-day raw lakes."""

    def __init__(self) -> None:
        self.books: dict[str, BinanceOrderBook] = {}
        self.gates: dict[str, BinanceDepthSequenceGate] = {}
        self.channel_counts: dict[str, int] = {}
        self.raw_event_count = 0

    def apply(self, event: RawMarketEvent) -> None:
        if event.exchange != "binance":
            raise BinanceReplayError("BinanceReplaySession accepts only Binance events")
        self.raw_event_count += 1
        self.channel_counts[event.channel] = self.channel_counts.get(event.channel, 0) + 1
        if event.channel != "orderbook":
            return

        book = self.books.setdefault(event.symbol, BinanceOrderBook(event.symbol))
        gate = self.gates.setdefault(event.symbol, BinanceDepthSequenceGate(event.symbol))

        if event.message_type == "snapshot":
            payload = event.payload()
            update_id = _required_int(payload.get("lastUpdateId"), "lastUpdateId")
            book.load_snapshot(payload.get("bids"), payload.get("asks"), update_id)
            gate.bootstrap(snapshot_update_id=update_id, connection_id=event.connection_id)
            return

        accepted = gate.apply(event)
        if not accepted:
            return  # stale relative to the bootstrap snapshot - silently dropped, per protocol
        message = _stream_message(event.payload())
        update_id = _required_int(message.get("u"), "u")
        book.apply_delta(message.get("b"), message.get("a"), update_id)

    def report(self) -> ReplayReport:
        replayed_books = {
            symbol: book.snapshot()
            for symbol, book in sorted(self.books.items())
            if book.is_ready
        }
        checksum_payload = {
            "raw_event_count": self.raw_event_count,
            "channel_counts": self.channel_counts,
            "orderbooks": {
                symbol: asdict(book) for symbol, book in sorted(replayed_books.items())
            },
        }
        encoded = json.dumps(checksum_payload, sort_keys=True, separators=(",", ":"))
        return ReplayReport(
            raw_event_count=self.raw_event_count,
            channel_counts=dict(sorted(self.channel_counts.items())),
            orderbooks=replayed_books,
            replay_checksum=hashlib.sha256(encoded.encode("utf-8")).hexdigest(),
        )


def replay_binance(events: list[RawMarketEvent]) -> ReplayReport:
    """Replay a bounded list in receive order and fail closed on uncertainty."""
    ordered = sorted(
        events,
        key=lambda event: (event.receive_ts_ns, event.receive_sequence, event.event_id),
    )
    return replay_binance_stream(ordered)


def replay_binance_stream(events: Iterable[RawMarketEvent]) -> ReplayReport:
    """Replay an already stream-ordered iterable with bounded memory."""
    session = BinanceReplaySession()
    for event in events:
        session.apply(event)
    return session.report()


def _stream_message(payload: dict[str, Any]) -> dict[str, Any]:
    data = payload.get("data", payload)
    if not isinstance(data, dict):
        raise BinanceReplayError("combined stream data must be an object")
    return data


def _levels(value: Any, name: str) -> list[tuple[Decimal, Decimal]]:
    if not isinstance(value, list):
        raise BinanceReplayError(f"order-book {name} must be a list")
    result = []
    for level in value:
        if not isinstance(level, list) or len(level) != 2:
            raise BinanceReplayError(f"invalid order-book {name} level: {level!r}")
        try:
            price = Decimal(str(level[0]))
            size = Decimal(str(level[1]))
        except InvalidOperation as exc:
            raise BinanceReplayError(f"invalid decimal order-book level: {level!r}") from exc
        if not price.is_finite() or not size.is_finite() or price <= 0 or size < 0:
            raise BinanceReplayError(f"invalid numeric order-book level: {level!r}")
        result.append((price, size))
    return result


def _apply_levels(side: dict[Decimal, Decimal], levels: list[tuple[Decimal, Decimal]]) -> None:
    for price, size in levels:
        if size == 0:
            side.pop(price, None)
        else:
            side[price] = size


def _validate_book(
    symbol: str, bids: dict[Decimal, Decimal], asks: dict[Decimal, Decimal]
) -> None:
    if not bids or not asks:
        raise InvalidOrderBook(f"{symbol} order book has an empty side")
    best_bid = max(bids)
    best_ask = min(asks)
    if best_bid >= best_ask:
        raise InvalidOrderBook(f"{symbol} order book is crossed: bid={best_bid}, ask={best_ask}")


def _required_int(value: Any, name: str) -> int:
    if value is None or isinstance(value, bool):
        raise BinanceReplayError(f"missing integer {name}")
    try:
        return int(value)
    except (TypeError, ValueError) as exc:
        raise BinanceReplayError(f"invalid integer {name}: {value!r}") from exc


def _decimal_text(value: Decimal) -> str:
    return format(value, "f")


def _book_checksum(
    symbol: str,
    update_id: int,
    bids: list[tuple[Decimal, Decimal]],
    asks: list[tuple[Decimal, Decimal]],
) -> str:
    value = {
        "symbol": symbol,
        "update_id": update_id,
        "bids": [[_decimal_text(price), _decimal_text(size)] for price, size in bids],
        "asks": [[_decimal_text(price), _decimal_text(size)] for price, size in asks],
    }
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()
