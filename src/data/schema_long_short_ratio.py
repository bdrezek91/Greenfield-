"""Canonical schema for the long/short account-ratio dataset - the
positioning-ratio counterpart to src/data/schema_funding.py's
funding-rate/open-interest schemas.

Kept separate for the same reason schema_funding.py is: a different
dataset shape (no OHLC columns) with its own storage partitions - see
src/data/storage.py.
"""

from __future__ import annotations

import pandas as pd

LONG_SHORT_RATIO_COLUMNS: tuple[str, ...] = ("timestamp", "symbol", "buy_ratio", "sell_ratio")
LONG_SHORT_RATIO_DTYPES: dict[str, str] = {
    "buy_ratio": "float64",
    "sell_ratio": "float64",
    "symbol": "string",
}


def empty_long_short_ratio_frame() -> pd.DataFrame:
    df = pd.DataFrame(
        {
            col: pd.Series(dtype=LONG_SHORT_RATIO_DTYPES.get(col, "float64"))
            for col in LONG_SHORT_RATIO_COLUMNS
        }
    )
    df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True)
    return df


def assert_long_short_ratio_schema(df: pd.DataFrame) -> None:
    missing = [c for c in LONG_SHORT_RATIO_COLUMNS if c not in df.columns]
    if missing:
        raise ValueError(f"long/short ratio frame is missing required columns: {missing}")
    if df["timestamp"].dt.tz is None:
        raise ValueError("timestamp column must be timezone-aware (UTC)")
