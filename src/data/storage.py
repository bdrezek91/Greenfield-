"""Parquet storage, partitioned by symbol/timeframe/year-month.

Datasets live under DATA_DIR (see .env.example) and are never committed to
git - see docs/DATA.md.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from src.data.schema import assert_schema, empty_klines_frame
from src.data.schema_funding import (
    assert_funding_schema,
    assert_open_interest_schema,
    empty_funding_frame,
    empty_open_interest_frame,
)
from src.data.schema_long_short_ratio import (
    assert_long_short_ratio_schema,
    empty_long_short_ratio_frame,
)


def _partition_dir(data_dir: Path, symbol: str, timeframe: str, year_month: str) -> Path:
    return Path(data_dir) / "klines" / symbol / timeframe / f"{year_month}.parquet"


def _funding_partition_dir(data_dir: Path, symbol: str, year_month: str) -> Path:
    return Path(data_dir) / "funding" / symbol / f"{year_month}.parquet"


def _open_interest_partition_dir(
    data_dir: Path, symbol: str, interval_time: str, year_month: str
) -> Path:
    return Path(data_dir) / "open_interest" / symbol / interval_time / f"{year_month}.parquet"


def _long_short_ratio_partition_dir(
    data_dir: Path, symbol: str, period: str, year_month: str
) -> Path:
    return Path(data_dir) / "long_short_ratio" / symbol / period / f"{year_month}.parquet"


def write_klines(df: pd.DataFrame, data_dir: Path) -> list[Path]:
    """Write a klines frame, splitting it into monthly partitions.

    Existing partitions are merged (not overwritten) so repeated/incremental
    downloads are safe: new rows are appended and duplicates removed.
    """
    if df.empty:
        return []
    assert_schema(df)

    written: list[Path] = []
    df = df.copy()
    df["_year_month"] = df["timestamp"].dt.strftime("%Y-%m")

    for (symbol, timeframe, year_month), group in df.groupby(
        ["symbol", "timeframe", "_year_month"], observed=True
    ):
        path = _partition_dir(data_dir, str(symbol), str(timeframe), str(year_month))
        path.parent.mkdir(parents=True, exist_ok=True)
        group = group.drop(columns="_year_month")

        if path.exists():
            existing = pd.read_parquet(path)
            group = pd.concat([existing, group], ignore_index=True)
            group = group.drop_duplicates(subset=["timestamp", "symbol", "timeframe"])
            group = group.sort_values("timestamp").reset_index(drop=True)

        group.to_parquet(path, index=False)
        written.append(path)

    return written


def read_klines(
    data_dir: Path,
    symbol: str,
    timeframe: str,
    start: pd.Timestamp | None = None,
    end: pd.Timestamp | None = None,
) -> pd.DataFrame:
    """Read all monthly partitions for `symbol`/`timeframe`, optionally sliced
    to [start, end].
    """
    partition_dir = Path(data_dir) / "klines" / symbol / timeframe
    if not partition_dir.exists():
        return empty_klines_frame()

    frames = [pd.read_parquet(p) for p in sorted(partition_dir.glob("*.parquet"))]
    if not frames:
        return empty_klines_frame()

    df = pd.concat(frames, ignore_index=True)
    df = df.sort_values("timestamp").reset_index(drop=True)

    if start is not None:
        df = df[df["timestamp"] >= start]
    if end is not None:
        df = df[df["timestamp"] <= end]
    return df.reset_index(drop=True)


def write_funding(df: pd.DataFrame, data_dir: Path) -> list[Path]:
    """Write a funding-rate frame, splitting it into monthly partitions.
    Same merge-not-overwrite behavior as `write_klines`.
    """
    if df.empty:
        return []
    assert_funding_schema(df)

    written: list[Path] = []
    df = df.copy()
    df["_year_month"] = df["timestamp"].dt.strftime("%Y-%m")

    for (symbol, year_month), group in df.groupby(["symbol", "_year_month"], observed=True):
        path = _funding_partition_dir(data_dir, str(symbol), str(year_month))
        path.parent.mkdir(parents=True, exist_ok=True)
        group = group.drop(columns="_year_month")

        if path.exists():
            existing = pd.read_parquet(path)
            group = pd.concat([existing, group], ignore_index=True)
            group = group.drop_duplicates(subset=["timestamp", "symbol"])
            group = group.sort_values("timestamp").reset_index(drop=True)

        group.to_parquet(path, index=False)
        written.append(path)

    return written


def read_funding(
    data_dir: Path,
    symbol: str,
    start: pd.Timestamp | None = None,
    end: pd.Timestamp | None = None,
) -> pd.DataFrame:
    """Read all monthly funding-rate partitions for `symbol`, optionally
    sliced to [start, end].
    """
    partition_dir = Path(data_dir) / "funding" / symbol
    if not partition_dir.exists():
        return empty_funding_frame()

    frames = [pd.read_parquet(p) for p in sorted(partition_dir.glob("*.parquet"))]
    if not frames:
        return empty_funding_frame()

    df = pd.concat(frames, ignore_index=True)
    df = df.sort_values("timestamp").reset_index(drop=True)

    if start is not None:
        df = df[df["timestamp"] >= start]
    if end is not None:
        df = df[df["timestamp"] <= end]
    return df.reset_index(drop=True)


def write_open_interest(df: pd.DataFrame, data_dir: Path, interval_time: str) -> list[Path]:
    """Write an open-interest frame, splitting it into monthly partitions.
    `interval_time` (Bybit's aggregation window, e.g. "1h") is part of the
    partition path since the same symbol can have OI series at multiple
    intervals - same merge-not-overwrite behavior as `write_klines`.
    """
    if df.empty:
        return []
    assert_open_interest_schema(df)

    written: list[Path] = []
    df = df.copy()
    df["_year_month"] = df["timestamp"].dt.strftime("%Y-%m")

    for (symbol, year_month), group in df.groupby(["symbol", "_year_month"], observed=True):
        path = _open_interest_partition_dir(data_dir, str(symbol), interval_time, str(year_month))
        path.parent.mkdir(parents=True, exist_ok=True)
        group = group.drop(columns="_year_month")

        if path.exists():
            existing = pd.read_parquet(path)
            group = pd.concat([existing, group], ignore_index=True)
            group = group.drop_duplicates(subset=["timestamp", "symbol"])
            group = group.sort_values("timestamp").reset_index(drop=True)

        group.to_parquet(path, index=False)
        written.append(path)

    return written


def read_open_interest(
    data_dir: Path,
    symbol: str,
    interval_time: str,
    start: pd.Timestamp | None = None,
    end: pd.Timestamp | None = None,
) -> pd.DataFrame:
    """Read all monthly open-interest partitions for `symbol`/`interval_time`,
    optionally sliced to [start, end].
    """
    partition_dir = Path(data_dir) / "open_interest" / symbol / interval_time
    if not partition_dir.exists():
        return empty_open_interest_frame()

    frames = [pd.read_parquet(p) for p in sorted(partition_dir.glob("*.parquet"))]
    if not frames:
        return empty_open_interest_frame()

    df = pd.concat(frames, ignore_index=True)
    df = df.sort_values("timestamp").reset_index(drop=True)

    if start is not None:
        df = df[df["timestamp"] >= start]
    if end is not None:
        df = df[df["timestamp"] <= end]
    return df.reset_index(drop=True)


def write_long_short_ratio(df: pd.DataFrame, data_dir: Path, period: str) -> list[Path]:
    """Write a long/short account-ratio frame, splitting it into monthly
    partitions. `period` (Bybit's aggregation window, e.g. "5min") is part
    of the partition path since the same symbol can have ratio series at
    multiple periods - same merge-not-overwrite behavior as `write_klines`.
    """
    if df.empty:
        return []
    assert_long_short_ratio_schema(df)

    written: list[Path] = []
    df = df.copy()
    df["_year_month"] = df["timestamp"].dt.strftime("%Y-%m")

    for (symbol, year_month), group in df.groupby(["symbol", "_year_month"], observed=True):
        path = _long_short_ratio_partition_dir(data_dir, str(symbol), period, str(year_month))
        path.parent.mkdir(parents=True, exist_ok=True)
        group = group.drop(columns="_year_month")

        if path.exists():
            existing = pd.read_parquet(path)
            group = pd.concat([existing, group], ignore_index=True)
            group = group.drop_duplicates(subset=["timestamp", "symbol"])
            group = group.sort_values("timestamp").reset_index(drop=True)

        group.to_parquet(path, index=False)
        written.append(path)

    return written


def read_long_short_ratio(
    data_dir: Path,
    symbol: str,
    period: str,
    start: pd.Timestamp | None = None,
    end: pd.Timestamp | None = None,
) -> pd.DataFrame:
    """Read all monthly long/short-ratio partitions for `symbol`/`period`,
    optionally sliced to [start, end].
    """
    partition_dir = Path(data_dir) / "long_short_ratio" / symbol / period
    if not partition_dir.exists():
        return empty_long_short_ratio_frame()

    frames = [pd.read_parquet(p) for p in sorted(partition_dir.glob("*.parquet"))]
    if not frames:
        return empty_long_short_ratio_frame()

    df = pd.concat(frames, ignore_index=True)
    df = df.sort_values("timestamp").reset_index(drop=True)

    if start is not None:
        df = df[df["timestamp"] >= start]
    if end is not None:
        df = df[df["timestamp"] <= end]
    return df.reset_index(drop=True)
