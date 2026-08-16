"""Maintains one side of Bybit's v5 order book WebSocket protocol client-side:
a `snapshot` message replaces the book entirely, `delta` messages upsert or
remove individual price levels (size "0" means remove) - see
https://bybit-exchange.github.io/docs/v5/websocket/public/orderbook (not
fetchable from this session, see src/data/microstructure_collector.py's
module docstring; documented here from the publicly known v5 protocol
shape, validate on first live run).

Deliberately reduces the book to a top-of-book summary rather than storing
raw depth - see src/data/microstructure_schema.py.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class OrderBookSummary:
    best_bid: float
    best_ask: float
    mid_price: float
    spread: float
    bid_qty_top: float
    ask_qty_top: float
    imbalance: float  # (bid_qty_top - ask_qty_top) / (bid_qty_top + ask_qty_top), in [-1, 1]


class OrderBookState:
    """Client-side order book for one symbol. `top_n` controls how many
    price levels (best-first) are summed into the imbalance summary -
    Bybit's own "50" in the `orderbook.50.SYMBOL` topic name is the
    server-side depth streamed, independent of this.
    """

    def __init__(self, top_n: int = 10) -> None:
        self._top_n = top_n
        self._bids: dict[float, float] = {}
        self._asks: dict[float, float] = {}

    def apply_snapshot(self, bids: list[list[str]], asks: list[list[str]]) -> None:
        self._bids = {float(p): float(q) for p, q in bids if float(q) > 0}
        self._asks = {float(p): float(q) for p, q in asks if float(q) > 0}

    def apply_delta(self, bids: list[list[str]], asks: list[list[str]]) -> None:
        for price_str, qty_str in bids:
            self._upsert(self._bids, price_str, qty_str)
        for price_str, qty_str in asks:
            self._upsert(self._asks, price_str, qty_str)

    @staticmethod
    def _upsert(book_side: dict[float, float], price_str: str, qty_str: str) -> None:
        price, qty = float(price_str), float(qty_str)
        if qty == 0:
            book_side.pop(price, None)
        else:
            book_side[price] = qty

    @property
    def is_ready(self) -> bool:
        return bool(self._bids) and bool(self._asks)

    def summary(self) -> OrderBookSummary | None:
        """None until at least one snapshot with both sides has been applied."""
        if not self.is_ready:
            return None

        best_bid = max(self._bids)
        best_ask = min(self._asks)
        bid_qty_top = sum(
            q for p, q in sorted(self._bids.items(), reverse=True)[: self._top_n]
        )
        ask_qty_top = sum(q for p, q in sorted(self._asks.items())[: self._top_n])
        total = bid_qty_top + ask_qty_top
        imbalance = (bid_qty_top - ask_qty_top) / total if total > 0 else 0.0

        return OrderBookSummary(
            best_bid=best_bid,
            best_ask=best_ask,
            mid_price=(best_bid + best_ask) / 2,
            spread=best_ask - best_bid,
            bid_qty_top=bid_qty_top,
            ask_qty_top=ask_qty_top,
            imbalance=imbalance,
        )
