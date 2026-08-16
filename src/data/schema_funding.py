"""Canonical schemas for funding-rate and open-interest datasets - the
funding/open-interest counterpart to src/data/schema.py's OHLCV schema.

Kept as a separate module (not added to schema.py) since these are a
different shape of dataset (no OHLC columns) with their own storage
partitions - see src/data/storage.py.
"""

from __future__ import annotations

import pandas as pd

FUNDING_COLUMNS: tuple[str, ...] = ("timestamp", "symbol", "funding_rate")
FUNDING_DTYPES: dict[str, str] = {"funding_rate": "float64", "symbol": "string"}

OPEN_INTEREST_COLUMNS: tuple[str, ...] = ("timestamp", "symbol", "open_interest")
OPEN_INTEREST_DTYPES: dict[str, str] = {"open_interest": "float64", "symbol": "string"}


def empty_funding_frame() -> pd.DataFrame:
    df = pd.DataFrame(
        {col: pd.Series(dtype=FUNDING_DTYPES.get(col, "float64")) for col in FUNDING_COLUMNS}
    )
    df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True)
    return df


def empty_open_interest_frame() -> pd.DataFrame:
    df = pd.DataFrame(
        {
            col: pd.Series(dtype=OPEN_INTEREST_DTYPES.get(col, "float64"))
            for col in OPEN_INTEREST_COLUMNS
        }
    )
    df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True)
    return df


def assert_funding_schema(df: pd.DataFrame) -> None:
    missing = [c for c in FUNDING_COLUMNS if c not in df.columns]
    if missing:
        raise ValueError(f"funding-rate frame is missing required columns: {missing}")
    if df["timestamp"].dt.tz is None:
        raise ValueError("timestamp column must be timezone-aware (UTC)")


def assert_open_interest_schema(df: pd.DataFrame) -> None:
    missing = [c for c in OPEN_INTEREST_COLUMNS if c not in df.columns]
    if missing:
        raise ValueError(f"open-interest frame is missing required columns: {missing}")
    if df["timestamp"].dt.tz is None:
        raise ValueError("timestamp column must be timezone-aware (UTC)")
