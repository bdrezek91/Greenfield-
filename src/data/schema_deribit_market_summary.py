"""Canonical schema for Deribit's per-currency market summary snapshot -
covers perpetual, dated futures, AND options in one uniform shape, via
`GET /public/get_book_summary_by_currency`.

This is a deliberate, disclosed design choice over expanding the WS raw
collector's per-instrument L2 subscriptions to dated futures/options: live
verification in this session found 998 active BTC option instruments and
886 active ETH ones (`GET /public/get_instruments?kind=option`) - two to
three orders of magnitude more than the 2-instrument
(`INITIAL_V2_DERIBIT_INSTRUMENTS`) architecture every per-symbol
sequence-gate/health/queue in this project assumes. Subscribing to full
L2 books for ~2000 option series is operationally impractical and not
what the master plan's "options: IV, skew i term structure" goal actually
needs - `get_book_summary_by_currency` returns `mark_iv` (implied
volatility), `underlying_price`/`underlying_index`, open interest, and
mark/bid/ask price for EVERY instrument of a currency+kind in one call,
which is exactly the raw material a later feature-layer skew/term-
structure computation needs, without per-instrument WS connections.

Dated futures (13 per currency, live-verified) are included too, via
`kind=future` (which also includes the perpetual - not filtered out here:
this summary's open_interest/volume_usd/mark_price fields are a
genuinely different, complementary shape from the WS collector's raw L2
book state, not a duplicate of it).

`mark_iv`/`underlying_price`/`underlying_index` are option-only fields -
`None` for a future/perpetual row, never fabricated as 0.
"""

from __future__ import annotations

import pandas as pd

DERIBIT_MARKET_SUMMARY_COLUMNS: tuple[str, ...] = (
    "timestamp",
    "instrument_name",
    "kind",
    "base_currency",
    "bid_price",
    "ask_price",
    "mark_price",
    "mid_price",
    "last_price",
    "open_interest",
    "volume",
    "volume_usd",
    "mark_iv",
    "underlying_price",
    "underlying_index",
)
DERIBIT_MARKET_SUMMARY_DTYPES: dict[str, str] = {
    "instrument_name": "string",
    "kind": "string",
    "base_currency": "string",
    "bid_price": "float64",
    "ask_price": "float64",
    "mark_price": "float64",
    "mid_price": "float64",
    "last_price": "float64",
    "open_interest": "float64",
    "volume": "float64",
    "volume_usd": "float64",
    "mark_iv": "float64",
    "underlying_price": "float64",
    "underlying_index": "string",
}


def empty_deribit_market_summary_frame() -> pd.DataFrame:
    df = pd.DataFrame(
        {
            col: pd.Series(dtype=DERIBIT_MARKET_SUMMARY_DTYPES.get(col, "float64"))
            for col in DERIBIT_MARKET_SUMMARY_COLUMNS
        }
    )
    df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True)
    return df


def assert_deribit_market_summary_schema(df: pd.DataFrame) -> None:
    missing = [c for c in DERIBIT_MARKET_SUMMARY_COLUMNS if c not in df.columns]
    if missing:
        raise ValueError(
            f"Deribit market-summary frame is missing required columns: {missing}"
        )
    if df["timestamp"].dt.tz is None:
        raise ValueError("timestamp column must be timezone-aware (UTC)")
