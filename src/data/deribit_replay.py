"""Deterministic Deribit L2 order-book replay from immutable raw events.

Structurally mirrors src/data/okx_replay.py - Deribit self-bootstraps from
the stream's own `message_type == "snapshot"` notification (per-symbol,
`type: "snapshot"`), the same as OKX, so there is no REST-snapshot
prerequisite the way Cycle 19 had to add for Binance. Sequence continuity
reuses `DeribitBookSequenceGate` (src/data/deribit_adapter.py) directly
for `change_id`/`prev_change_id` continuity, already the tested source of
truth used by the live collector.

The one real protocol difference from every other exchange here: Deribit
book levels are `[action, price, amount]` triplets with an explicit
`action` field (`"new"`/`"change"`/`"delete"`), not a `[price, size]` pair
where `size == 0` implies delete. `"delete"` entries are required to carry
`amount == 0` (per src/data/deribit_normalized_event.py's own validation,
mirrored here) - `action` is what determines the operation, `amount` is
not inferred from.

`DeribitBookSequenceGate.apply` never returns `False` (unlike OKX's
heartbeat case or Binance's stale-event case) - every call either
succeeds or raises, so there is no "accepted but skip" branch needed here.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable
from dataclasses import asdict, dataclass
from decimal import Decimal, InvalidOperation
from typing import Any

from src.data.deribit_adapter import (
    DeribitBookSequenceGate,
    DeribitReplayError,
    DeribitSequenceGap,
    DeribitSnapshotRequired,
)
from src.data.raw_event import RawMarketEvent

__all__ = [
    "DeribitBookSequenceGate",
    "DeribitOrderBook",
    "DeribitReplayError",
    "DeribitReplaySession",
    "DeribitSequenceGap",
    "DeribitSnapshotRequired",
    "InvalidOrderBook",
    "ReplayReport",
    "ReplayedBook",
    "replay_deribit",
    "replay_deribit_stream",
]


class InvalidOrderBook(DeribitReplayError):
    pass


@dataclass(frozen=True, slots=True)
class ReplayedBook:
    symbol: str
    change_id: int
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


class DeribitOrderBook:
    """Exact decimal L2 state, advanced by snapshot/delta messages already
    accepted by a `DeribitBookSequenceGate`."""

    def __init__(self, symbol: str) -> None:
        self.symbol = symbol
        self._bids: dict[Decimal, Decimal] = {}
        self._asks: dict[Decimal, Decimal] = {}
        self.change_id: int | None = None

    @property
    def is_ready(self) -> bool:
        return bool(self._bids) and bool(self._asks) and self.change_id is not None

    def apply_message(self, message_type: str, data: dict[str, Any], change_id: int) -> None:
        bids = _levels(data.get("bids"), "bids")
        asks = _levels(data.get("asks"), "asks")
        if message_type == "snapshot":
            next_bids = {price: size for price, size in bids if size > 0}
            next_asks = {price: size for price, size in asks if size > 0}
        else:
            if not self.is_ready:
                raise DeribitSnapshotRequired(
                    f"{self.symbol} delta arrived before a valid snapshot"
                )
            next_bids = dict(self._bids)
            next_asks = dict(self._asks)
            _apply_levels(next_bids, bids)
            _apply_levels(next_asks, asks)
        _validate_book(self.symbol, next_bids, next_asks)
        self._bids = next_bids
        self._asks = next_asks
        self.change_id = change_id

    def snapshot(self) -> ReplayedBook:
        if not self.is_ready or self.change_id is None:
            raise DeribitSnapshotRequired(f"{self.symbol} has no valid snapshot")
        bids = sorted(self._bids.items(), reverse=True)
        asks = sorted(self._asks.items())
        checksum = _book_checksum(self.symbol, self.change_id, bids, asks)
        return ReplayedBook(
            symbol=self.symbol,
            change_id=self.change_id,
            bid_levels=len(bids),
            ask_levels=len(asks),
            best_bid=_decimal_text(bids[0][0]),
            best_ask=_decimal_text(asks[0][0]),
            checksum=checksum,
        )


class DeribitReplaySession:
    """Incremental replay suitable for multi-day raw lakes."""

    def __init__(self) -> None:
        self.books: dict[str, DeribitOrderBook] = {}
        self.gates: dict[str, DeribitBookSequenceGate] = {}
        self.channel_counts: dict[str, int] = {}
        self.raw_event_count = 0

    def apply(self, event: RawMarketEvent) -> None:
        if event.exchange != "deribit":
            raise DeribitReplayError("DeribitReplaySession accepts only Deribit events")
        self.raw_event_count += 1
        self.channel_counts[event.channel] = self.channel_counts.get(event.channel, 0) + 1
        if event.channel != "orderbook":
            return

        gate = self.gates.setdefault(event.symbol, DeribitBookSequenceGate(event.symbol))
        gate.apply(event)  # raises on any discontinuity; never returns False for Deribit

        book = self.books.setdefault(event.symbol, DeribitOrderBook(event.symbol))
        data = _book_data(event.payload())
        change_id = _required_int(data.get("change_id"), "change_id")
        book.apply_message(event.message_type, data, change_id)

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


def replay_deribit(events: list[RawMarketEvent]) -> ReplayReport:
    """Replay a bounded list in receive order and fail closed on uncertainty."""
    ordered = sorted(
        events,
        key=lambda event: (event.receive_ts_ns, event.receive_sequence, event.event_id),
    )
    return replay_deribit_stream(ordered)


def replay_deribit_stream(events: Iterable[RawMarketEvent]) -> ReplayReport:
    """Replay an already stream-ordered iterable with bounded memory."""
    session = DeribitReplaySession()
    for event in events:
        session.apply(event)
    return session.report()


def _book_data(message: dict[str, Any]) -> dict[str, Any]:
    params = message.get("params")
    if not isinstance(params, dict) or not isinstance(params.get("data"), dict):
        raise DeribitReplayError("Deribit book notification must contain one data object")
    return params["data"]


def _levels(value: Any, name: str) -> list[tuple[Decimal, Decimal]]:
    if not isinstance(value, list):
        raise DeribitReplayError(f"order-book {name} must be a list")
    result = []
    for level in value:
        if not isinstance(level, list) or len(level) != 3:
            raise DeribitReplayError(f"invalid order-book {name} level: {level!r}")
        action = str(level[0])
        if action not in {"new", "change", "delete"}:
            raise DeribitReplayError(f"invalid order-book {name} action: {action!r}")
        try:
            price = Decimal(str(level[1]))
            size = Decimal(str(level[2]))
        except InvalidOperation as exc:
            raise DeribitReplayError(f"invalid decimal order-book level: {level!r}") from exc
        if not price.is_finite() or not size.is_finite() or price <= 0 or size < 0:
            raise DeribitReplayError(f"invalid numeric order-book level: {level!r}")
        if action == "delete":
            if size != 0:
                raise DeribitReplayError(f"delete level must have zero size: {level!r}")
            size = Decimal(0)
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
        raise DeribitReplayError(f"missing integer {name}")
    try:
        return int(value)
    except (TypeError, ValueError) as exc:
        raise DeribitReplayError(f"invalid integer {name}: {value!r}") from exc


def _decimal_text(value: Decimal) -> str:
    return format(value, "f")


def _book_checksum(
    symbol: str,
    change_id: int,
    bids: list[tuple[Decimal, Decimal]],
    asks: list[tuple[Decimal, Decimal]],
) -> str:
    value = {
        "symbol": symbol,
        "change_id": change_id,
        "bids": [[_decimal_text(price), _decimal_text(size)] for price, size in bids],
        "asks": [[_decimal_text(price), _decimal_text(size)] for price, size in asks],
    }
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()
