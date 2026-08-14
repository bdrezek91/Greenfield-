"""Canonical OHLCV schema shared by ingestion, storage and validation."""

from __future__ import annotations

import pandas as pd

COLUMNS: tuple[str, ...] = (
    "timestamp",
    "open",
    "high",
    "low",
    "close",
    "volume",
    "turnover",
    "symbol",
    "timeframe",
)

DTYPES: dict[str, str] = {
    "open": "float64",
    "high": "float64",
    "low": "float64",
    "close": "float64",
    "volume": "float64",
    "turnover": "float64",
    "symbol": "string",
    "timeframe": "string",
}


def empty_klines_frame() -> pd.DataFrame:
    """An empty, correctly-typed OHLCV frame (useful as a merge/validation base)."""
    df = pd.DataFrame({col: pd.Series(dtype=DTYPES.get(col, "float64")) for col in COLUMNS})
    df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True)
    return df


def assert_schema(df: pd.DataFrame) -> None:
    missing = [c for c in COLUMNS if c not in df.columns]
    if missing:
        raise ValueError(f"klines frame is missing required columns: {missing}")
    if df["timestamp"].dt.tz is None:
        raise ValueError("timestamp column must be timezone-aware (UTC)")
