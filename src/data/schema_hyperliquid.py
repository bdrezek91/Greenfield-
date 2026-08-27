"""Canonical schemas for Hyperliquid research market data - asset context
snapshots (funding/OI/mark/oracle/mid/premium in one row), funding-rate
history, cross-venue predicted funding, and top-of-book (BBO) snapshots.

Separate `hyperliquid_*` storage namespace (see
src/data/hyperliquid_storage.py) - zero risk to Bybit/Binance/OKX storage,
and Hyperliquid's `coin` values ("BTC", not "BTCUSDT"/"BTC-USDT-SWAP")
would otherwise be ambiguous against those venues' own symbol formats.
"""

from __future__ import annotations

import pandas as pd

HYPERLIQUID_ASSET_CONTEXT_COLUMNS: tuple[str, ...] = (
    "timestamp",
    "coin",
    "funding",
    "open_interest",
    "mark_px",
    "oracle_px",
    "mid_px",
    "premium",
    "day_ntl_vlm",
)
HYPERLIQUID_ASSET_CONTEXT_DTYPES: dict[str, str] = {
    "coin": "string",
    "funding": "float64",
    "open_interest": "float64",
    "mark_px": "float64",
    "oracle_px": "float64",
    "mid_px": "float64",
    "premium": "float64",
    "day_ntl_vlm": "float64",
}

HYPERLIQUID_FUNDING_HISTORY_COLUMNS: tuple[str, ...] = (
    "timestamp",
    "coin",
    "funding_rate",
    "premium",
)
HYPERLIQUID_FUNDING_HISTORY_DTYPES: dict[str, str] = {
    "coin": "string",
    "funding_rate": "float64",
    "premium": "float64",
}

HYPERLIQUID_PREDICTED_FUNDING_COLUMNS: tuple[str, ...] = (
    "timestamp",
    "coin",
    "venue",
    "funding_rate",
    "next_funding_time",
    "funding_interval_hours",
)
HYPERLIQUID_PREDICTED_FUNDING_DTYPES: dict[str, str] = {
    "coin": "string",
    "venue": "string",
    "funding_rate": "float64",
    "funding_interval_hours": "float64",
}

HYPERLIQUID_BBO_COLUMNS: tuple[str, ...] = (
    "timestamp",
    "coin",
    "bid_price",
    "bid_size",
    "ask_price",
    "ask_size",
)
HYPERLIQUID_BBO_DTYPES: dict[str, str] = {
    "coin": "string",
    "bid_price": "float64",
    "bid_size": "float64",
    "ask_price": "float64",
    "ask_size": "float64",
}


def _empty_frame(columns: tuple[str, ...], dtypes: dict[str, str]) -> pd.DataFrame:
    df = pd.DataFrame({col: pd.Series(dtype=dtypes.get(col, "float64")) for col in columns})
    df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True)
    return df


def _assert_schema(df: pd.DataFrame, columns: tuple[str, ...], name: str) -> None:
    missing = [c for c in columns if c not in df.columns]
    if missing:
        raise ValueError(f"Hyperliquid {name} frame is missing required columns: {missing}")
    if df["timestamp"].dt.tz is None:
        raise ValueError("timestamp column must be timezone-aware (UTC)")


def empty_hyperliquid_asset_context_frame() -> pd.DataFrame:
    return _empty_frame(HYPERLIQUID_ASSET_CONTEXT_COLUMNS, HYPERLIQUID_ASSET_CONTEXT_DTYPES)


def assert_hyperliquid_asset_context_schema(df: pd.DataFrame) -> None:
    _assert_schema(df, HYPERLIQUID_ASSET_CONTEXT_COLUMNS, "asset-context")


def empty_hyperliquid_funding_history_frame() -> pd.DataFrame:
    return _empty_frame(HYPERLIQUID_FUNDING_HISTORY_COLUMNS, HYPERLIQUID_FUNDING_HISTORY_DTYPES)


def assert_hyperliquid_funding_history_schema(df: pd.DataFrame) -> None:
    _assert_schema(df, HYPERLIQUID_FUNDING_HISTORY_COLUMNS, "funding-history")


def empty_hyperliquid_predicted_funding_frame() -> pd.DataFrame:
    return _empty_frame(HYPERLIQUID_PREDICTED_FUNDING_COLUMNS, HYPERLIQUID_PREDICTED_FUNDING_DTYPES)


def assert_hyperliquid_predicted_funding_schema(df: pd.DataFrame) -> None:
    _assert_schema(df, HYPERLIQUID_PREDICTED_FUNDING_COLUMNS, "predicted-funding")


def empty_hyperliquid_bbo_frame() -> pd.DataFrame:
    return _empty_frame(HYPERLIQUID_BBO_COLUMNS, HYPERLIQUID_BBO_DTYPES)


def assert_hyperliquid_bbo_schema(df: pd.DataFrame) -> None:
    _assert_schema(df, HYPERLIQUID_BBO_COLUMNS, "BBO")
