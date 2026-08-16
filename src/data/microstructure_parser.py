"""Pure parsing functions from Bybit v5 public WebSocket message shapes
(orderbook, publicTrade, liquidation topics) into this project's canonical
rows (src/data/microstructure_schema.py).

Deliberately separated from src/data/microstructure_collector.py's live
WebSocket wiring so this parsing logic - the part that can actually be
wrong about Bybit's message shape - is fully unit-testable without a
network connection. Message shapes documented here from Bybit's public v5
WebSocket docs (not fetchable from this session - see the collector
module's docstring); validate against a real message on first live run.
"""

from __future__ import annotations

from typing import Any

import pandas as pd

from src.data.orderbook_state import OrderBookState


def apply_orderbook_message(state: OrderBookState, message: dict[str, Any]) -> dict | None:
    """Apply an `orderbook.{depth}.{symbol}` message to `state` and return a
    canonical row (src/data/microstructure_schema.ORDERBOOK_COLUMNS) if the
    book is ready after this update, else None (e.g. a delta arriving
    before any snapshot).
    """
    msg_type = message.get("type")
    data = message.get("data", {})
    bids = data.get("b", [])
    asks = data.get("a", [])

    if msg_type == "snapshot":
        state.apply_snapshot(bids, asks)
    elif msg_type == "delta":
        state.apply_delta(bids, asks)
    else:
        raise ValueError(f"unrecognized orderbook message type: {msg_type!r}")

    summary = state.summary()
    if summary is None:
        return None

    symbol = data.get("s")
    ts_ms = message.get("ts")
    return {
        "timestamp": pd.Timestamp(ts_ms, unit="ms", tz="UTC"),
        "symbol": symbol,
        "best_bid": summary.best_bid,
        "best_ask": summary.best_ask,
        "mid_price": summary.mid_price,
        "spread": summary.spread,
        "bid_qty_top": summary.bid_qty_top,
        "ask_qty_top": summary.ask_qty_top,
        "imbalance": summary.imbalance,
    }


def parse_trade_message(message: dict[str, Any]) -> list[dict]:
    """A `publicTrade.{symbol}` message carries a list of trades in `data`."""
    rows = []
    for entry in message.get("data", []):
        rows.append(
            {
                "timestamp": pd.Timestamp(int(entry["T"]), unit="ms", tz="UTC"),
                "symbol": entry["s"],
                "price": float(entry["p"]),
                "size": float(entry["v"]),
                "side": entry["S"],  # "Buy" or "Sell" - the taker/aggressor side
                "trade_id": entry["i"],
            }
        )
    return rows


def parse_liquidation_message(message: dict[str, Any]) -> dict:
    """A `liquidation.{symbol}` message carries a single liquidation event
    in `data`.
    """
    data = message["data"]
    return {
        "timestamp": pd.Timestamp(int(data["updatedTime"]), unit="ms", tz="UTC"),
        "symbol": data["symbol"],
        "side": data["side"],
        "price": float(data["price"]),
        "size": float(data["size"]),
    }
