"""Canonical schemas for OKX SWAP (perpetual) derivatives statistics -
open interest and the long/short account ratio.

Deliberately separate from src/data/schema_binance_derivatives.py: OKX's
`GET /api/v5/public/open-interest` reports `oi`/`oiCcy`/`oiUsd` (three
distinct units - contracts, base currency, USD notional), a richer shape
than Binance's `sumOpenInterest`/`sumOpenInterestValue`. OKX's
`GET /api/v5/rubik/stat/contracts/long-short-account-ratio-contract`
returns only a single ratio value per timestamp (`[ts, ratio]` pairs) -
no separate long/short percentage breakdown the way Binance's
`longAccount`/`shortAccount` gives, so there is nothing to force-fit a
richer schema onto without inventing data OKX doesn't provide.

Storage lives under top-level `okx_open_interest/`/`okx_long_short_ratio/`
directories (see src/data/okx_derivatives_storage.py) - distinct from
Bybit's and Binance's directories, so instId strings (e.g.
"BTC-USDT-SWAP") can never collide with either.
"""

from __future__ import annotations

import pandas as pd

OKX_OPEN_INTEREST_COLUMNS: tuple[str, ...] = (
    "timestamp",
    "inst_id",
    "open_interest",
    "open_interest_ccy",
    "open_interest_usd",
)
OKX_OPEN_INTEREST_DTYPES: dict[str, str] = {
    "open_interest": "float64",
    "open_interest_ccy": "float64",
    "open_interest_usd": "float64",
    "inst_id": "string",
}

OKX_LONG_SHORT_RATIO_COLUMNS: tuple[str, ...] = ("timestamp", "inst_id", "long_short_ratio")
OKX_LONG_SHORT_RATIO_DTYPES: dict[str, str] = {
    "long_short_ratio": "float64",
    "inst_id": "string",
}


def empty_okx_open_interest_frame() -> pd.DataFrame:
    df = pd.DataFrame(
        {
            col: pd.Series(dtype=OKX_OPEN_INTEREST_DTYPES.get(col, "float64"))
            for col in OKX_OPEN_INTEREST_COLUMNS
        }
    )
    df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True)
    return df


def assert_okx_open_interest_schema(df: pd.DataFrame) -> None:
    missing = [c for c in OKX_OPEN_INTEREST_COLUMNS if c not in df.columns]
    if missing:
        raise ValueError(f"OKX open-interest frame is missing required columns: {missing}")
    if df["timestamp"].dt.tz is None:
        raise ValueError("timestamp column must be timezone-aware (UTC)")


def empty_okx_long_short_ratio_frame() -> pd.DataFrame:
    df = pd.DataFrame(
        {
            col: pd.Series(dtype=OKX_LONG_SHORT_RATIO_DTYPES.get(col, "float64"))
            for col in OKX_LONG_SHORT_RATIO_COLUMNS
        }
    )
    df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True)
    return df


def assert_okx_long_short_ratio_schema(df: pd.DataFrame) -> None:
    missing = [c for c in OKX_LONG_SHORT_RATIO_COLUMNS if c not in df.columns]
    if missing:
        raise ValueError(f"OKX long/short-ratio frame is missing required columns: {missing}")
    if df["timestamp"].dt.tz is None:
        raise ValueError("timestamp column must be timezone-aware (UTC)")
