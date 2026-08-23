"""Canonical schema for near-ATM Deribit option ticker snapshots
(src/data/deribit_option_ticker_client.py/_collector.py, Cycle 36) - the
option-surface-quality counterpart to
src/data/schema_deribit_market_summary.py (which covers every active
instrument in bulk but lacks bid_iv/ask_iv/delta).

`option_strike`/`option_right`/`expiry_utc` come from
src/data/deribit_option_instrument.py's instrument-name parser, not from
the ticker response itself (Deribit's ticker payload does not restate
them). `delta` is `None` only if Deribit's own `greeks` object is absent
for an instrument (never fabricated).
"""

from __future__ import annotations

import pandas as pd

DERIBIT_OPTION_TICKER_COLUMNS: tuple[str, ...] = (
    "timestamp",
    "instrument_name",
    "base_currency",
    "expiry_utc",
    "option_strike",
    "option_right",
    "mark_price",
    "bid_price",
    "ask_price",
    "mark_iv",
    "bid_iv",
    "ask_iv",
    "delta",
    "open_interest",
    "underlying_price",
)
DERIBIT_OPTION_TICKER_DTYPES: dict[str, str] = {
    "instrument_name": "string",
    "base_currency": "string",
    "option_strike": "float64",
    "option_right": "string",
    "mark_price": "float64",
    "bid_price": "float64",
    "ask_price": "float64",
    "mark_iv": "float64",
    "bid_iv": "float64",
    "ask_iv": "float64",
    "delta": "float64",
    "open_interest": "float64",
    "underlying_price": "float64",
}


def empty_deribit_option_ticker_frame() -> pd.DataFrame:
    df = pd.DataFrame(
        {
            col: pd.Series(dtype=DERIBIT_OPTION_TICKER_DTYPES.get(col, "float64"))
            for col in DERIBIT_OPTION_TICKER_COLUMNS
        }
    )
    df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True)
    df["expiry_utc"] = pd.to_datetime(df["expiry_utc"], utc=True)
    return df


def assert_deribit_option_ticker_schema(df: pd.DataFrame) -> None:
    missing = [c for c in DERIBIT_OPTION_TICKER_COLUMNS if c not in df.columns]
    if missing:
        raise ValueError(f"Deribit option-ticker frame is missing required columns: {missing}")
    if df["timestamp"].dt.tz is None:
        raise ValueError("timestamp column must be timezone-aware (UTC)")
    if df["expiry_utc"].dt.tz is None:
        raise ValueError("expiry_utc column must be timezone-aware (UTC)")
