"""Parquet storage, partitioned by symbol/timeframe/year-month.

Datasets live under DATA_DIR (see .env.example) and are never committed to
git - see docs/DATA.md.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from src.data.schema import assert_schema, empty_klines_frame


def _partition_dir(data_dir: Path, symbol: str, timeframe: str, year_month: str) -> Path:
    return Path(data_dir) / "klines" / symbol / timeframe / f"{year_month}.parquet"


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
