"""Deterministic OKX L2 order-book replay from immutable raw events.

Structurally mirrors src/data/bybit_replay.py and src/data/binance_replay.py,
adapted to OKX's protocol:

- Sequence continuity reuses `OkxSequenceGate` (src/data/okx_adapter.py)
  directly rather than reimplementing the `seqId`/`prevSeqId` contract -
  already the tested source of truth used by the live collector.
- Unlike Binance, OKX self-bootstraps from the stream's own
  `message_type == "snapshot"` message (per-connection, action="snapshot")
  - there is no REST-snapshot prerequisite the way Cycle 19 had to add for
  Binance. Every OKX Bronze file, old or new, is fully replayable as long
  as it starts from (or contains) a snapshot message for each symbol.
- OKX's book levels are `[price, size, liquidated_orders_count,
  order_count]` (4 elements), not the 2-element `[price, size]` pairs
  Bybit/Binance use - only the first two fields are meaningful for book
  reconstruction, the rest are ignored here (see
  src/data/okx_normalized_event.py's identical `len(level) < 2` tolerance).
- `OkxSequenceGate.apply` already classifies pure heartbeat messages
  (`seqId == prevSeqId` with empty `bids`/`asks`) as a no-op, returning
  `False` - this replay tool treats that exactly like a live collector
  would: counted, but no book mutation attempted.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable
from dataclasses import asdict, dataclass
from decimal import Decimal, InvalidOperation
from typing import Any

from src.data.okx_adapter import (
    OkxReplayError,
    OkxSequenceGap,
    OkxSequenceGate,
    OkxSnapshotRequired,
)
from src.data.raw_event import RawMarketEvent

__all__ = [
    "InvalidOrderBook",
    "OkxOrderBook",
    "OkxReplayError",
    "OkxReplaySession",
    "OkxSequenceGap",
    "OkxSequenceGate",
    "OkxSnapshotRequired",
    "ReplayReport",
    "ReplayedBook",
    "replay_okx",
    "replay_okx_stream",
]


class InvalidOrderBook(OkxReplayError):
    pass


@dataclass(frozen=True, slots=True)
class ReplayedBook:
    symbol: str
    sequence: int
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


class OkxOrderBook:
    """Exact decimal L2 state, advanced by snapshot/delta messages already
    accepted by an `OkxSequenceGate`."""

    def __init__(self, symbol: str) -> None:
        self.symbol = symbol
        self._bids: dict[Decimal, Decimal] = {}
        self._asks: dict[Decimal, Decimal] = {}
        self.sequence: int | None = None

    @property
    def is_ready(self) -> bool:
        return bool(self._bids) and bool(self._asks) and self.sequence is not None

    def apply_message(self, message_type: str, data: dict[str, Any], sequence: int) -> None:
        bids = _levels(data.get("bids"), "bids")
        asks = _levels(data.get("asks"), "asks")
        if message_type == "snapshot":
            next_bids = {price: size for price, size in bids if size > 0}
            next_asks = {price: size for price, size in asks if size > 0}
        else:
            if not self.is_ready:
                raise OkxSnapshotRequired(f"{self.symbol} delta arrived before a valid snapshot")
            next_bids = dict(self._bids)
            next_asks = dict(self._asks)
            _apply_levels(next_bids, bids)
            _apply_levels(next_asks, asks)
        _validate_book(self.symbol, next_bids, next_asks)
        self._bids = next_bids
        self._asks = next_asks
        self.sequence = sequence

    def snapshot(self) -> ReplayedBook:
        if not self.is_ready or self.sequence is None:
            raise OkxSnapshotRequired(f"{self.symbol} has no valid snapshot")
        bids = sorted(self._bids.items(), reverse=True)
        asks = sorted(self._asks.items())
        checksum = _book_checksum(self.symbol, self.sequence, bids, asks)
        return ReplayedBook(
            symbol=self.symbol,
            sequence=self.sequence,
            bid_levels=len(bids),
            ask_levels=len(asks),
            best_bid=_decimal_text(bids[0][0]),
            best_ask=_decimal_text(asks[0][0]),
            checksum=checksum,
        )


class OkxReplaySession:
    """Incremental replay suitable for multi-day raw lakes."""

    def __init__(self) -> None:
        self.books: dict[str, OkxOrderBook] = {}
        self.gates: dict[str, OkxSequenceGate] = {}
        self.channel_counts: dict[str, int] = {}
        self.raw_event_count = 0

    def apply(self, event: RawMarketEvent) -> None:
        if event.exchange != "okx":
            raise OkxReplayError("OkxReplaySession accepts only OKX events")
        self.raw_event_count += 1
        self.channel_counts[event.channel] = self.channel_counts.get(event.channel, 0) + 1
        if event.channel != "orderbook":
            return

        gate = self.gates.setdefault(event.symbol, OkxSequenceGate(event.symbol))
        accepted = gate.apply(event)
        if not accepted:
            return  # pure heartbeat - no book change, per OkxSequenceGate.apply

        book = self.books.setdefault(event.symbol, OkxOrderBook(event.symbol))
        data = _first_data(event.payload())
        sequence = _required_int(data.get("seqId"), "seqId")
        book.apply_message(event.message_type, data, sequence)

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


def replay_okx(events: list[RawMarketEvent]) -> ReplayReport:
    """Replay a bounded list in receive order and fail closed on uncertainty."""
    ordered = sorted(
        events,
        key=lambda event: (event.receive_ts_ns, event.receive_sequence, event.event_id),
    )
    return replay_okx_stream(ordered)


def replay_okx_stream(events: Iterable[RawMarketEvent]) -> ReplayReport:
    """Replay an already stream-ordered iterable with bounded memory."""
    session = OkxReplaySession()
    for event in events:
        session.apply(event)
    return session.report()


def _first_data(message: dict[str, Any]) -> dict[str, Any]:
    data = message.get("data")
    if not isinstance(data, list) or len(data) != 1 or not isinstance(data[0], dict):
        raise OkxReplayError("OKX book message must contain one data object")
    return data[0]


def _levels(value: Any, name: str) -> list[tuple[Decimal, Decimal]]:
    if not isinstance(value, list):
        raise OkxReplayError(f"order-book {name} must be a list")
    result = []
    for level in value:
        if not isinstance(level, list) or len(level) < 2:
            raise OkxReplayError(f"invalid order-book {name} level: {level!r}")
        try:
            price = Decimal(str(level[0]))
            size = Decimal(str(level[1]))
        except InvalidOperation as exc:
            raise OkxReplayError(f"invalid decimal order-book level: {level!r}") from exc
        if not price.is_finite() or not size.is_finite() or price <= 0 or size < 0:
            raise OkxReplayError(f"invalid numeric order-book level: {level!r}")
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
        raise OkxReplayError(f"missing integer {name}")
    try:
        return int(value)
    except (TypeError, ValueError) as exc:
        raise OkxReplayError(f"invalid integer {name}: {value!r}") from exc


def _decimal_text(value: Decimal) -> str:
    return format(value, "f")


def _book_checksum(
    symbol: str,
    sequence: int,
    bids: list[tuple[Decimal, Decimal]],
    asks: list[tuple[Decimal, Decimal]],
) -> str:
    value = {
        "symbol": symbol,
        "sequence": sequence,
        "bids": [[_decimal_text(price), _decimal_text(size)] for price, size in bids],
        "asks": [[_decimal_text(price), _decimal_text(size)] for price, size in asks],
    }
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()
