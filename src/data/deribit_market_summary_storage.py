"""Parquet storage for Deribit's per-currency market summary snapshots -
the Deribit counterpart to src/data/binance_derivatives_storage.py /
src/data/okx_derivatives_storage.py.

Unlike those (an appended, ever-growing time series with a natural
"newer than last" cutoff), every poll here re-covers the SAME set of
instruments with updated numbers - there is no "new rows only" filter to
apply; each poll is its own complete, uniquely-timestamped snapshot batch.
Deduplication on write is still exact-match (`timestamp`, `instrument_name`)
so re-running a poll for a timestamp that was already written is a no-op,
not a duplicate.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from src.data.schema_deribit_market_summary import (
    assert_deribit_market_summary_schema,
    empty_deribit_market_summary_frame,
)


def _partition_dir(data_dir: Path, currency: str, kind: str, year_month: str) -> Path:
    return (
        Path(data_dir)
        / "deribit_market_summary"
        / currency
        / kind
        / f"{year_month}.parquet"
    )


def write_deribit_market_summary(
    df: pd.DataFrame, data_dir: Path, currency: str, kind: str
) -> list[Path]:
    """Write a market-summary batch, splitting it into monthly partitions."""
    if df.empty:
        return []
    assert_deribit_market_summary_schema(df)

    written: list[Path] = []
    df = df.copy()
    df["_year_month"] = df["timestamp"].dt.strftime("%Y-%m")
    for year_month, group in df.groupby("_year_month", observed=True):
        path = _partition_dir(data_dir, currency, kind, str(year_month))
        path.parent.mkdir(parents=True, exist_ok=True)
        group = group.drop(columns="_year_month")
        if path.exists():
            existing = pd.read_parquet(path)
            group = pd.concat([existing, group], ignore_index=True)
            group = group.drop_duplicates(subset=["timestamp", "instrument_name"])
            group = group.sort_values(["timestamp", "instrument_name"]).reset_index(drop=True)
        group.to_parquet(path, index=False)
        written.append(path)
    return written


def read_deribit_market_summary(
    data_dir: Path,
    currency: str,
    kind: str,
    start: pd.Timestamp | None = None,
    end: pd.Timestamp | None = None,
) -> pd.DataFrame:
    """Read all monthly partitions for `currency`/`kind`, optionally sliced
    to [start, end]."""
    partition_dir = Path(data_dir) / "deribit_market_summary" / currency / kind
    if not partition_dir.exists():
        return empty_deribit_market_summary_frame()

    frames = [pd.read_parquet(p) for p in sorted(partition_dir.glob("*.parquet"))]
    if not frames:
        return empty_deribit_market_summary_frame()

    df = pd.concat(frames, ignore_index=True)
    df = df.sort_values(["timestamp", "instrument_name"]).reset_index(drop=True)
    if start is not None:
        df = df[df["timestamp"] >= start]
    if end is not None:
        df = df[df["timestamp"] <= end]
    return df.reset_index(drop=True)
