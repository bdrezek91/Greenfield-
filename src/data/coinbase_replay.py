"""Deterministic Coinbase L2 order-book replay from immutable raw events.

Structurally mirrors src/data/bybit_replay.py / binance_replay.py /
okx_replay.py, but Coinbase's protocol forces a genuinely different
design (see src/data/coinbase_raw_collector.py's module docstring and
src/data/coinbase_adapter.py::CoinbaseConnectionSequenceGate's own
docstring for the live protocol probing this is built on):

- `sequence_num` is CONNECTION-GLOBAL, shared by every message the
  exchange sends on one connection - every channel, every product,
  including the automatic `subscriptions` acknowledgement. It is NOT a
  per-product, per-channel counter the way Bybit's `u`, Binance's `u`/`pu`,
  or OKX's `seqId`/`prevSeqId` are. `CoinbaseLevel2SequenceGate` (which
  assumes the latter) was live-verified to be WRONG and is deliberately
  not used here, exactly as the live collector deliberately does not wire
  it - reusing it would reproduce the same spurious-gap bug this replay
  tool would otherwise silently inherit.
- Consequently there is exactly ONE `CoinbaseConnectionSequenceGate` per
  replay session (not one per product/symbol like every other exchange's
  gate here) verifying overall stream continuity. A gap/duplicate/rollback
  on that gate means the WHOLE connection's data from that point is
  suspect, not just one product's - it fails the whole replay, the same
  fail-closed behavior as every other exchange's replay tool in this repo.
- Per-product L2 book reconstruction applies snapshot/delta messages in
  receive order with NO additional per-product sequence check of its own
  - continuity is fully delegated to the single connection-global gate
  above. A book's `last_sequence_num` field is purely informational (the
  connection-global counter value of the event that last touched that
  book), not an invariant the book itself enforces.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable
from dataclasses import asdict, dataclass
from decimal import Decimal, InvalidOperation
from typing import Any

from src.data.coinbase_adapter import (
    CoinbaseConnectionSequenceGate,
    CoinbaseReplayError,
    CoinbaseSequenceDuplicate,
    CoinbaseSequenceGap,
    CoinbaseSequenceRollback,
)
from src.data.raw_event import RawMarketEvent

__all__ = [
    "CoinbaseConnectionSequenceGate",
    "CoinbaseOrderBook",
    "CoinbaseReplayError",
    "CoinbaseReplaySession",
    "CoinbaseSequenceDuplicate",
    "CoinbaseSequenceGap",
    "CoinbaseSequenceRollback",
    "InvalidOrderBook",
    "ReplayReport",
    "ReplayedBook",
    "replay_coinbase",
    "replay_coinbase_stream",
]


class InvalidOrderBook(CoinbaseReplayError):
    pass


@dataclass(frozen=True, slots=True)
class ReplayedBook:
    symbol: str
    last_sequence_num: int | None
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


class CoinbaseOrderBook:
    """Exact decimal L2 state for one product, advanced by snapshot/delta
    `events` entries already accepted by the session's connection-global
    gate."""

    def __init__(self, symbol: str) -> None:
        self.symbol = symbol
        self._bids: dict[Decimal, Decimal] = {}
        self._asks: dict[Decimal, Decimal] = {}
        self.last_sequence_num: int | None = None

    @property
    def is_ready(self) -> bool:
        return bool(self._bids) and bool(self._asks)

    def load_snapshot(self, entries: list[dict[str, Any]], sequence_num: int | None) -> None:
        levels = _levels(entries)
        next_bids = {price: size for side, price, size in levels if side == "bid" and size > 0}
        next_asks = {price: size for side, price, size in levels if side == "ask" and size > 0}
        _validate_book(self.symbol, next_bids, next_asks)
        self._bids = next_bids
        self._asks = next_asks
        self.last_sequence_num = sequence_num

    def apply_delta(self, entries: list[dict[str, Any]], sequence_num: int | None) -> None:
        if not self.is_ready:
            raise CoinbaseReplayError(f"{self.symbol} delta arrived before a valid snapshot")
        next_bids = dict(self._bids)
        next_asks = dict(self._asks)
        for side, price, size in _levels(entries):
            target = next_bids if side == "bid" else next_asks
            if size == 0:
                target.pop(price, None)
            else:
                target[price] = size
        _validate_book(self.symbol, next_bids, next_asks)
        self._bids = next_bids
        self._asks = next_asks
        self.last_sequence_num = sequence_num

    def snapshot(self) -> ReplayedBook:
        if not self.is_ready:
            raise CoinbaseReplayError(f"{self.symbol} has no valid snapshot")
        bids = sorted(self._bids.items(), reverse=True)
        asks = sorted(self._asks.items())
        checksum = _book_checksum(self.symbol, self.last_sequence_num, bids, asks)
        return ReplayedBook(
            symbol=self.symbol,
            last_sequence_num=self.last_sequence_num,
            bid_levels=len(bids),
            ask_levels=len(asks),
            best_bid=_decimal_text(bids[0][0]),
            best_ask=_decimal_text(asks[0][0]),
            checksum=checksum,
        )


class CoinbaseReplaySession:
    """Incremental replay suitable for multi-day raw lakes. One
    connection-global sequence gate for the whole session (see module
    docstring), one order book per product.
    """

    def __init__(self) -> None:
        self.books: dict[str, CoinbaseOrderBook] = {}
        self.connection_gate = CoinbaseConnectionSequenceGate()
        self.channel_counts: dict[str, int] = {}
        self.raw_event_count = 0

    def apply(self, event: RawMarketEvent) -> None:
        if event.exchange != "coinbase":
            raise CoinbaseReplayError("CoinbaseReplaySession accepts only Coinbase events")
        self.raw_event_count += 1
        self.channel_counts[event.channel] = self.channel_counts.get(event.channel, 0) + 1
        self.connection_gate.observe(event)  # fail-closed for the whole session on any gap

        if event.channel != "orderbook":
            return
        if event.symbol in {"ALL", "MULTI"}:
            raise CoinbaseReplayError(
                f"L2 event must resolve to exactly one product, got {event.symbol!r}"
            )
        if event.message_type not in {"snapshot", "delta"}:
            raise CoinbaseReplayError(
                f"unexpected Coinbase L2 message_type: {event.message_type!r}"
            )

        book = self.books.setdefault(event.symbol, CoinbaseOrderBook(event.symbol))
        message = event.payload()
        entries = message.get("events")
        if not isinstance(entries, list):
            raise CoinbaseReplayError("Coinbase events must be a list")
        if event.message_type == "snapshot":
            book.load_snapshot(entries, event.sequence)
        else:
            book.apply_delta(entries, event.sequence)

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


def replay_coinbase(events: list[RawMarketEvent]) -> ReplayReport:
    """Replay a bounded list in receive order and fail closed on uncertainty."""
    ordered = sorted(
        events,
        key=lambda event: (event.receive_ts_ns, event.receive_sequence, event.event_id),
    )
    return replay_coinbase_stream(ordered)


def replay_coinbase_stream(events: Iterable[RawMarketEvent]) -> ReplayReport:
    """Replay an already stream-ordered iterable with bounded memory."""
    session = CoinbaseReplaySession()
    for event in events:
        session.apply(event)
    return session.report()


def _levels(entries: list[dict[str, Any]]) -> list[tuple[str, Decimal, Decimal]]:
    result: list[tuple[str, Decimal, Decimal]] = []
    for entry in entries:
        if not isinstance(entry, dict):
            raise CoinbaseReplayError("Coinbase L2 event must be an object")
        updates = entry.get("updates")
        if not isinstance(updates, list):
            raise CoinbaseReplayError("Coinbase L2 updates must be a list")
        for update in updates:
            if not isinstance(update, dict):
                raise CoinbaseReplayError("Coinbase L2 update must be an object")
            raw_side = str(update.get("side") or "").lower()
            if raw_side not in {"bid", "offer"}:
                raise CoinbaseReplayError(f"invalid Coinbase book side: {raw_side!r}")
            side = "ask" if raw_side == "offer" else "bid"
            try:
                price = Decimal(str(update.get("price_level")))
                size = Decimal(str(update.get("new_quantity")))
            except InvalidOperation as exc:
                raise CoinbaseReplayError(f"invalid decimal L2 level: {update!r}") from exc
            if not price.is_finite() or not size.is_finite() or price <= 0 or size < 0:
                raise CoinbaseReplayError(f"invalid numeric L2 level: {update!r}")
            result.append((side, price, size))
    return result


def _validate_book(
    symbol: str, bids: dict[Decimal, Decimal], asks: dict[Decimal, Decimal]
) -> None:
    if not bids or not asks:
        raise InvalidOrderBook(f"{symbol} order book has an empty side")
    best_bid = max(bids)
    best_ask = min(asks)
    if best_bid >= best_ask:
        raise InvalidOrderBook(f"{symbol} order book is crossed: bid={best_bid}, ask={best_ask}")


def _decimal_text(value: Decimal) -> str:
    return format(value, "f")


def _book_checksum(
    symbol: str,
    last_sequence_num: int | None,
    bids: list[tuple[Decimal, Decimal]],
    asks: list[tuple[Decimal, Decimal]],
) -> str:
    value = {
        "symbol": symbol,
        "last_sequence_num": last_sequence_num,
        "bids": [[_decimal_text(price), _decimal_text(size)] for price, size in bids],
        "asks": [[_decimal_text(price), _decimal_text(size)] for price, size in asks],
    }
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()
