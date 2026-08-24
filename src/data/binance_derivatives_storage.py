"""Parquet storage for Binance derivatives-statistics datasets
(open-interest history, long/short account-ratio history) - the Binance
counterpart to the relevant parts of src/data/storage.py.

Deliberately a separate module rather than adding functions to
src/data/storage.py: these write to their own top-level directories
(`binance_open_interest/`, `binance_long_short_ratio/`), so there is zero
risk of touching the already-working Bybit read/write paths in
storage.py, and zero chance of a Binance symbol (e.g. BTCUSDT) colliding
with Bybit's identically-named symbol under the existing bare
`open_interest/`/`long_short_ratio/` directories.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from src.data.atomic_parquet import merge_atomic_parquet
from src.data.schema_binance_derivatives import (
    assert_binance_long_short_ratio_schema,
    assert_binance_open_interest_schema,
    empty_binance_long_short_ratio_frame,
    empty_binance_open_interest_frame,
)


def _binance_open_interest_partition_dir(
    data_dir: Path, symbol: str, period: str, year_month: str
) -> Path:
    return Path(data_dir) / "binance_open_interest" / symbol / period / f"{year_month}.parquet"


def _binance_long_short_ratio_partition_dir(
    data_dir: Path, symbol: str, period: str, year_month: str
) -> Path:
    return (
        Path(data_dir) / "binance_long_short_ratio" / symbol / period / f"{year_month}.parquet"
    )


def _write_merged(df: pd.DataFrame, path: Path) -> None:
    merge_atomic_parquet(
        path, df, deduplicate_on=("timestamp", "symbol"), sort_by=("timestamp",)
    )


def write_binance_open_interest(df: pd.DataFrame, data_dir: Path, period: str) -> list[Path]:
    """Write a Binance open-interest frame, splitting it into monthly
    partitions. `period` (e.g. "5m") is part of the partition path since
    the same symbol can have OI series at multiple periods - same
    merge-not-overwrite behavior as src/data/storage.py::write_klines.
    """
    if df.empty:
        return []
    assert_binance_open_interest_schema(df)

    written: list[Path] = []
    df = df.copy()
    df["_year_month"] = df["timestamp"].dt.strftime("%Y-%m")
    for (symbol, year_month), group in df.groupby(["symbol", "_year_month"], observed=True):
        path = _binance_open_interest_partition_dir(data_dir, str(symbol), period, str(year_month))
        _write_merged(group.drop(columns="_year_month"), path)
        written.append(path)
    return written


def write_binance_long_short_ratio(df: pd.DataFrame, data_dir: Path, period: str) -> list[Path]:
    """Write a Binance long/short-ratio frame, splitting it into monthly
    partitions - same shape/behavior as `write_binance_open_interest`.
    """
    if df.empty:
        return []
    assert_binance_long_short_ratio_schema(df)

    written: list[Path] = []
    df = df.copy()
    df["_year_month"] = df["timestamp"].dt.strftime("%Y-%m")
    for (symbol, year_month), group in df.groupby(["symbol", "_year_month"], observed=True):
        path = _binance_long_short_ratio_partition_dir(
            data_dir, str(symbol), period, str(year_month)
        )
        _write_merged(group.drop(columns="_year_month"), path)
        written.append(path)
    return written


def read_binance_open_interest(
    data_dir: Path,
    symbol: str,
    period: str,
    start: pd.Timestamp | None = None,
    end: pd.Timestamp | None = None,
) -> pd.DataFrame:
    """Read all monthly Binance open-interest partitions for
    `symbol`/`period`, optionally sliced to [start, end].
    """
    partition_dir = Path(data_dir) / "binance_open_interest" / symbol / period
    if not partition_dir.exists():
        return empty_binance_open_interest_frame()

    frames = [pd.read_parquet(p) for p in sorted(partition_dir.glob("*.parquet"))]
    if not frames:
        return empty_binance_open_interest_frame()

    df = pd.concat(frames, ignore_index=True)
    df = df.sort_values("timestamp").reset_index(drop=True)
    if start is not None:
        df = df[df["timestamp"] >= start]
    if end is not None:
        df = df[df["timestamp"] <= end]
    return df.reset_index(drop=True)


def read_binance_long_short_ratio(
    data_dir: Path,
    symbol: str,
    period: str,
    start: pd.Timestamp | None = None,
    end: pd.Timestamp | None = None,
) -> pd.DataFrame:
    """Read all monthly Binance long/short-ratio partitions for
    `symbol`/`period`, optionally sliced to [start, end].
    """
    partition_dir = Path(data_dir) / "binance_long_short_ratio" / symbol / period
    if not partition_dir.exists():
        return empty_binance_long_short_ratio_frame()

    frames = [pd.read_parquet(p) for p in sorted(partition_dir.glob("*.parquet"))]
    if not frames:
        return empty_binance_long_short_ratio_frame()

    df = pd.concat(frames, ignore_index=True)
    df = df.sort_values("timestamp").reset_index(drop=True)
    if start is not None:
        df = df[df["timestamp"] >= start]
    if end is not None:
        df = df[df["timestamp"] <= end]
    return df.reset_index(drop=True)
