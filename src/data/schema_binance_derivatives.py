"""Canonical schemas for Binance USDT-M futures derivatives statistics -
open interest history and the global long/short account ratio.

Deliberately separate from src/data/schema_funding.py and
src/data/schema_long_short_ratio.py (Bybit's schemas) rather than reusing
them: Binance's `globalLongShortAccountRatio` reports `longAccount`/
`shortAccount`/`longShortRatio` directly, a materially different
representation from Bybit's `buyRatio`/`sellRatio` (order-volume based,
not account-count based per Bybit's docs) - force-fitting one exchange's
fields into another's column names would misrepresent what was actually
measured. Binance's open-interest history also reports a `open_interest_value`
(quote-currency notional) that Bybit's schema has no column for.

Storage lives under top-level `binance_open_interest/` and
`binance_long_short_ratio/` directories (see
src/data/binance_derivatives_storage.py) - distinct from the existing bare
`open_interest/`/`long_short_ratio/` directories Bybit's collectors write
to, so this can never collide with or migrate that already-working data.
"""

from __future__ import annotations

import pandas as pd

BINANCE_OPEN_INTEREST_COLUMNS: tuple[str, ...] = (
    "timestamp",
    "symbol",
    "open_interest",
    "open_interest_value",
)
BINANCE_OPEN_INTEREST_DTYPES: dict[str, str] = {
    "open_interest": "float64",
    "open_interest_value": "float64",
    "symbol": "string",
}

BINANCE_LONG_SHORT_RATIO_COLUMNS: tuple[str, ...] = (
    "timestamp",
    "symbol",
    "long_account",
    "short_account",
    "long_short_ratio",
)
BINANCE_LONG_SHORT_RATIO_DTYPES: dict[str, str] = {
    "long_account": "float64",
    "short_account": "float64",
    "long_short_ratio": "float64",
    "symbol": "string",
}


def empty_binance_open_interest_frame() -> pd.DataFrame:
    df = pd.DataFrame(
        {
            col: pd.Series(dtype=BINANCE_OPEN_INTEREST_DTYPES.get(col, "float64"))
            for col in BINANCE_OPEN_INTEREST_COLUMNS
        }
    )
    df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True)
    return df


def assert_binance_open_interest_schema(df: pd.DataFrame) -> None:
    missing = [c for c in BINANCE_OPEN_INTEREST_COLUMNS if c not in df.columns]
    if missing:
        raise ValueError(f"Binance open-interest frame is missing required columns: {missing}")
    if df["timestamp"].dt.tz is None:
        raise ValueError("timestamp column must be timezone-aware (UTC)")


def empty_binance_long_short_ratio_frame() -> pd.DataFrame:
    df = pd.DataFrame(
        {
            col: pd.Series(dtype=BINANCE_LONG_SHORT_RATIO_DTYPES.get(col, "float64"))
            for col in BINANCE_LONG_SHORT_RATIO_COLUMNS
        }
    )
    df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True)
    return df


def assert_binance_long_short_ratio_schema(df: pd.DataFrame) -> None:
    missing = [c for c in BINANCE_LONG_SHORT_RATIO_COLUMNS if c not in df.columns]
    if missing:
        raise ValueError(
            f"Binance long/short-ratio frame is missing required columns: {missing}"
        )
    if df["timestamp"].dt.tz is None:
        raise ValueError("timestamp column must be timezone-aware (UTC)")
