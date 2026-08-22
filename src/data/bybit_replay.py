"""Deterministic Bybit L2 and ticker replay from immutable raw events."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable
from dataclasses import asdict, dataclass
from decimal import Decimal, InvalidOperation
from typing import Any

from src.data.raw_event import RawMarketEvent


class ReplayError(RuntimeError):
    """A raw stream cannot be replayed without guessing market state."""


class SnapshotRequired(ReplayError):
    pass


class SequenceGap(ReplayError):
    def __init__(self, symbol: str, expected: int, observed: int) -> None:
        self.symbol = symbol
        self.expected = expected
        self.observed = observed
        super().__init__(
            f"{symbol} order-book update gap: expected u={expected}, observed u={observed}"
        )


class SequenceRegression(ReplayError):
    pass


class InvalidOrderBook(ReplayError):
    pass


@dataclass(frozen=True, slots=True)
class ReplayedBook:
    symbol: str
    update_id: int
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
    ticker_checksums: dict[str, str]
    replay_checksum: str

    def to_dict(self) -> dict[str, Any]:
        value = asdict(self)
        value["orderbooks"] = {
            symbol: asdict(book) for symbol, book in sorted(self.orderbooks.items())
        }
        return value


class BybitOrderBook:
    """Exact decimal L2 state with a strict contiguous ``u`` contract."""

    def __init__(self, symbol: str) -> None:
        self.symbol = symbol
        self._bids: dict[Decimal, Decimal] = {}
        self._asks: dict[Decimal, Decimal] = {}
        self.update_id: int | None = None
        self.sequence: int | None = None

    @property
    def is_ready(self) -> bool:
        return bool(self._bids) and bool(self._asks) and self.update_id is not None

    def invalidate(self) -> None:
        self._bids.clear()
        self._asks.clear()
        self.update_id = None
        self.sequence = None

    def apply_event(self, event: RawMarketEvent) -> None:
        if event.exchange != "bybit" or event.channel != "orderbook":
            raise ReplayError("BybitOrderBook accepts only Bybit orderbook events")
        if event.symbol != self.symbol:
            raise ReplayError(f"book {self.symbol} cannot accept event for {event.symbol}")
        self.apply_message(event.payload())

    def apply_message(self, message: dict[str, Any]) -> None:
        data = message.get("data")
        if not isinstance(data, dict):
            raise ReplayError(f"{self.symbol} order-book data must be an object")
        message_type = message.get("type")
        update_id = _required_int(data.get("u"), "u")
        sequence = _required_int(data.get("seq"), "seq")
        bids = _levels(data.get("b"), "b")
        asks = _levels(data.get("a"), "a")

        if message_type == "snapshot":
            next_bids = {price: size for price, size in bids if size > 0}
            next_asks = {price: size for price, size in asks if size > 0}
            _validate_book(self.symbol, next_bids, next_asks)
            self._bids = next_bids
            self._asks = next_asks
            self.update_id = update_id
            self.sequence = sequence
            return

        if message_type != "delta":
            raise ReplayError(f"unrecognized Bybit order-book type: {message_type!r}")
        if not self.is_ready or self.update_id is None or self.sequence is None:
            raise SnapshotRequired(f"{self.symbol} delta arrived before a valid snapshot")

        expected = self.update_id + 1
        if update_id > expected:
            self.invalidate()
            raise SequenceGap(self.symbol, expected, update_id)
        if update_id <= self.update_id:
            previous = self.update_id
            self.invalidate()
            raise SequenceRegression(
                f"{self.symbol} order-book u regressed or repeated: "
                f"previous={previous}, observed={update_id}"
            )
        if sequence <= self.sequence:
            previous_sequence = self.sequence
            self.invalidate()
            raise SequenceRegression(
                f"{self.symbol} cross sequence did not increase: "
                f"previous={previous_sequence}, observed={sequence}"
            )

        next_bids = dict(self._bids)
        next_asks = dict(self._asks)
        _apply_levels(next_bids, bids)
        _apply_levels(next_asks, asks)
        _validate_book(self.symbol, next_bids, next_asks)
        self._bids = next_bids
        self._asks = next_asks
        self.update_id = update_id
        self.sequence = sequence

    def snapshot(self) -> ReplayedBook:
        if not self.is_ready or self.update_id is None or self.sequence is None:
            raise SnapshotRequired(f"{self.symbol} has no valid snapshot")
        bids = sorted(self._bids.items(), reverse=True)
        asks = sorted(self._asks.items())
        checksum = _book_checksum(self.symbol, self.update_id, self.sequence, bids, asks)
        return ReplayedBook(
            symbol=self.symbol,
            update_id=self.update_id,
            sequence=self.sequence,
            bid_levels=len(bids),
            ask_levels=len(asks),
            best_bid=_decimal_text(bids[0][0]),
            best_ask=_decimal_text(asks[0][0]),
            checksum=checksum,
        )


class BybitTickerState:
    """Materialize Bybit derivative ticker snapshot-plus-delta messages."""

    def __init__(self, symbol: str) -> None:
        self.symbol = symbol
        self._data: dict[str, Any] | None = None
        self.sequence: int | None = None

    def invalidate(self) -> None:
        self._data = None
        self.sequence = None

    def apply_event(self, event: RawMarketEvent) -> None:
        if event.exchange != "bybit" or event.channel != "ticker":
            raise ReplayError("BybitTickerState accepts only Bybit ticker events")
        if event.symbol != self.symbol:
            raise ReplayError(f"ticker {self.symbol} cannot accept event for {event.symbol}")
        message = event.payload()
        data = message.get("data")
        if not isinstance(data, dict):
            raise ReplayError(f"{self.symbol} ticker data must be an object")
        sequence = _required_int(message.get("cs"), "cs")
        message_type = message.get("type")
        if message_type == "snapshot":
            self._data = dict(data)
            self.sequence = sequence
            return
        if message_type != "delta":
            raise ReplayError(f"unrecognized Bybit ticker type: {message_type!r}")
        if self._data is None or self.sequence is None:
            raise SnapshotRequired(f"{self.symbol} ticker delta arrived before snapshot")
        if sequence <= self.sequence:
            previous = self.sequence
            self.invalidate()
            raise SequenceRegression(
                f"{self.symbol} ticker sequence did not increase: "
                f"previous={previous}, observed={sequence}"
            )
        self._data.update(data)
        self.sequence = sequence

    def checksum(self) -> str:
        if self._data is None or self.sequence is None:
            raise SnapshotRequired(f"{self.symbol} has no ticker snapshot")
        materialized = {"sequence": self.sequence, "data": self._data}
        encoded = json.dumps(materialized, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


class BybitReplaySession:
    """Incremental replay suitable for multi-day raw lakes."""

    def __init__(self) -> None:
        self.books: dict[str, BybitOrderBook] = {}
        self.tickers: dict[str, BybitTickerState] = {}
        self.book_connections: dict[str, str] = {}
        self.ticker_connections: dict[str, str] = {}
        self.channel_counts: dict[str, int] = {}
        self.raw_event_count = 0

    def apply(self, event: RawMarketEvent) -> None:
        self.raw_event_count += 1
        self.channel_counts[event.channel] = self.channel_counts.get(event.channel, 0) + 1
        if event.channel == "orderbook":
            book = self.books.setdefault(event.symbol, BybitOrderBook(event.symbol))
            if self.book_connections.get(event.symbol) != event.connection_id:
                book.invalidate()
                self.book_connections[event.symbol] = event.connection_id
            book.apply_event(event)
        elif event.channel == "ticker":
            ticker = self.tickers.setdefault(event.symbol, BybitTickerState(event.symbol))
            if self.ticker_connections.get(event.symbol) != event.connection_id:
                ticker.invalidate()
                self.ticker_connections[event.symbol] = event.connection_id
            ticker.apply_event(event)

    def report(self) -> ReplayReport:
        replayed_books = {
            symbol: book.snapshot()
            for symbol, book in sorted(self.books.items())
            if book.is_ready
        }
        ticker_checksums = {
            symbol: ticker.checksum()
            for symbol, ticker in sorted(self.tickers.items())
            if ticker.sequence is not None
        }
        checksum_payload = {
            "raw_event_count": self.raw_event_count,
            "channel_counts": self.channel_counts,
            "orderbooks": {
                symbol: asdict(book) for symbol, book in sorted(replayed_books.items())
            },
            "ticker_checksums": ticker_checksums,
        }
        encoded = json.dumps(checksum_payload, sort_keys=True, separators=(",", ":"))
        return ReplayReport(
            raw_event_count=self.raw_event_count,
            channel_counts=dict(sorted(self.channel_counts.items())),
            orderbooks=replayed_books,
            ticker_checksums=ticker_checksums,
            replay_checksum=hashlib.sha256(encoded.encode("utf-8")).hexdigest(),
        )


def replay_bybit(events: list[RawMarketEvent]) -> ReplayReport:
    """Replay a bounded list in receive order and fail closed on uncertainty."""
    ordered = sorted(
        events,
        key=lambda event: (event.receive_ts_ns, event.receive_sequence, event.event_id),
    )
    return replay_bybit_stream(ordered)


def replay_bybit_stream(events: Iterable[RawMarketEvent]) -> ReplayReport:
    """Replay an already stream-ordered iterable with bounded memory."""
    session = BybitReplaySession()
    for event in events:
        session.apply(event)
    return session.report()


def _levels(value: Any, name: str) -> list[tuple[Decimal, Decimal]]:
    if not isinstance(value, list):
        raise ReplayError(f"order-book {name} must be a list")
    result = []
    for level in value:
        if not isinstance(level, list) or len(level) != 2:
            raise ReplayError(f"invalid order-book {name} level: {level!r}")
        try:
            price = Decimal(str(level[0]))
            size = Decimal(str(level[1]))
        except InvalidOperation as exc:
            raise ReplayError(f"invalid decimal order-book level: {level!r}") from exc
        if not price.is_finite() or not size.is_finite() or price <= 0 or size < 0:
            raise ReplayError(f"invalid numeric order-book level: {level!r}")
        result.append((price, size))
    return result


def _apply_levels(
    side: dict[Decimal, Decimal], levels: list[tuple[Decimal, Decimal]]
) -> None:
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
        raise InvalidOrderBook(
            f"{symbol} order book is crossed: bid={best_bid}, ask={best_ask}"
        )


def _required_int(value: Any, name: str) -> int:
    if value is None or isinstance(value, bool):
        raise ReplayError(f"missing integer {name}")
    try:
        return int(value)
    except (TypeError, ValueError) as exc:
        raise ReplayError(f"invalid integer {name}: {value!r}") from exc


def _decimal_text(value: Decimal) -> str:
    return format(value, "f")


def _book_checksum(
    symbol: str,
    update_id: int,
    sequence: int,
    bids: list[tuple[Decimal, Decimal]],
    asks: list[tuple[Decimal, Decimal]],
) -> str:
    value = {
        "symbol": symbol,
        "update_id": update_id,
        "sequence": sequence,
        "bids": [[_decimal_text(price), _decimal_text(size)] for price, size in bids],
        "asks": [[_decimal_text(price), _decimal_text(size)] for price, size in asks],
    }
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()
