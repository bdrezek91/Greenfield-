"""Parquet storage for near-ATM Deribit option ticker snapshots - the
per-instrument-ticker counterpart to
src/data/deribit_market_summary_storage.py. Same "every poll re-covers a
fresh, independently-timestamped batch" shape (not an appended series
with a "newer than last" cutoff) - (timestamp, instrument_name) dedup on
write makes a re-run of the same poll a no-op, not a duplicate.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from src.data.atomic_parquet import merge_atomic_parquet
from src.data.schema_deribit_option_ticker import (
    assert_deribit_option_ticker_schema,
    empty_deribit_option_ticker_frame,
)


def _partition_dir(data_dir: Path, currency: str, year_month: str) -> Path:
    return Path(data_dir) / "deribit_option_ticker" / currency / f"{year_month}.parquet"


def write_deribit_option_ticker(df: pd.DataFrame, data_dir: Path, currency: str) -> list[Path]:
    """Write an option-ticker batch, splitting it into monthly partitions."""
    if df.empty:
        return []
    assert_deribit_option_ticker_schema(df)

    written: list[Path] = []
    df = df.copy()
    df["_year_month"] = df["timestamp"].dt.strftime("%Y-%m")
    for year_month, group in df.groupby("_year_month", observed=True):
        path = _partition_dir(data_dir, currency, str(year_month))
        group = group.drop(columns="_year_month")
        merge_atomic_parquet(
            path, group,
            deduplicate_on=("timestamp", "instrument_name"),
            sort_by=("timestamp", "instrument_name"),
        )
        written.append(path)
    return written


def read_deribit_option_ticker(
    data_dir: Path,
    currency: str,
    start: pd.Timestamp | None = None,
    end: pd.Timestamp | None = None,
) -> pd.DataFrame:
    """Read all monthly partitions for `currency`, optionally sliced to
    [start, end]."""
    partition_dir = Path(data_dir) / "deribit_option_ticker" / currency
    if not partition_dir.exists():
        return empty_deribit_option_ticker_frame()

    frames = [pd.read_parquet(p) for p in sorted(partition_dir.glob("*.parquet"))]
    if not frames:
        return empty_deribit_option_ticker_frame()

    df = pd.concat(frames, ignore_index=True)
    df = df.sort_values(["timestamp", "instrument_name"]).reset_index(drop=True)
    if start is not None:
        df = df[df["timestamp"] >= start]
    if end is not None:
        df = df[df["timestamp"] <= end]
    return df.reset_index(drop=True)
