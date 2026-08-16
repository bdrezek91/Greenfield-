"""Canonical schemas for the three market-microstructure streams collected
live from Bybit's public WebSocket (order book, trade tape, liquidations) -
see src/data/microstructure_collector.py.

Unlike klines/funding/open-interest (backfillable from REST history), none
of these three can be backfilled - Bybit only streams them live. These
schemas exist so a live collector (scripts/collect_microstructure.py)
running continuously can accumulate a real history to eventually backtest
or feature-engineer against, starting from whenever collection began.
"""

from __future__ import annotations

import pandas as pd

# One row per order book update, already reduced to a top-of-book summary
# (not the raw depth array) - directly usable as an order-book-imbalance
# feature without needing to reconstruct book state at read time.
ORDERBOOK_COLUMNS: tuple[str, ...] = (
    "timestamp",
    "symbol",
    "best_bid",
    "best_ask",
    "mid_price",
    "spread",
    "bid_qty_top",
    "ask_qty_top",
    "imbalance",
)
ORDERBOOK_DTYPES: dict[str, str] = {
    "symbol": "string",
    "best_bid": "float64",
    "best_ask": "float64",
    "mid_price": "float64",
    "spread": "float64",
    "bid_qty_top": "float64",
    "ask_qty_top": "float64",
    "imbalance": "float64",
}

TRADE_COLUMNS: tuple[str, ...] = ("timestamp", "symbol", "price", "size", "side", "trade_id")
TRADE_DTYPES: dict[str, str] = {
    "symbol": "string",
    "price": "float64",
    "size": "float64",
    "side": "string",
    "trade_id": "string",
}

LIQUIDATION_COLUMNS: tuple[str, ...] = ("timestamp", "symbol", "side", "price", "size")
LIQUIDATION_DTYPES: dict[str, str] = {
    "symbol": "string",
    "side": "string",
    "price": "float64",
    "size": "float64",
}


def _empty_frame(columns: tuple[str, ...], dtypes: dict[str, str]) -> pd.DataFrame:
    df = pd.DataFrame({col: pd.Series(dtype=dtypes.get(col, "float64")) for col in columns})
    df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True)
    return df


def empty_orderbook_frame() -> pd.DataFrame:
    return _empty_frame(ORDERBOOK_COLUMNS, ORDERBOOK_DTYPES)


def empty_trade_frame() -> pd.DataFrame:
    return _empty_frame(TRADE_COLUMNS, TRADE_DTYPES)


def empty_liquidation_frame() -> pd.DataFrame:
    return _empty_frame(LIQUIDATION_COLUMNS, LIQUIDATION_DTYPES)
