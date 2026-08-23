"""Parquet storage for OKX derivatives-statistics datasets (open interest,
long/short account-ratio) - the OKX counterpart to
src/data/binance_derivatives_storage.py.

Separate module/directories (`okx_open_interest/`, `okx_long_short_ratio/`)
for the same reason as the Binance module: zero risk to the existing
Bybit storage.py code path, zero chance of an instId string colliding
with another exchange's identically-shaped symbol.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from src.data.schema_okx_derivatives import (
    assert_okx_long_short_ratio_schema,
    assert_okx_open_interest_schema,
    empty_okx_long_short_ratio_frame,
    empty_okx_open_interest_frame,
)


def _okx_open_interest_partition_dir(data_dir: Path, inst_id: str, year_month: str) -> Path:
    return Path(data_dir) / "okx_open_interest" / inst_id / f"{year_month}.parquet"


def _okx_long_short_ratio_partition_dir(
    data_dir: Path, inst_id: str, period: str, year_month: str
) -> Path:
    return Path(data_dir) / "okx_long_short_ratio" / inst_id / period / f"{year_month}.parquet"


def _write_merged(df: pd.DataFrame, path: Path, dedup_subset: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        existing = pd.read_parquet(path)
        df = pd.concat([existing, df], ignore_index=True)
        df = df.drop_duplicates(subset=dedup_subset)
        df = df.sort_values("timestamp").reset_index(drop=True)
    df.to_parquet(path, index=False)


def write_okx_open_interest(df: pd.DataFrame, data_dir: Path) -> list[Path]:
    """Write an OKX open-interest frame, splitting it into monthly
    partitions. No `period` dimension (unlike long/short-ratio) since the
    snapshot endpoint has no aggregation window - see
    src/data/okx_derivatives_client.py's module docstring.
    """
    if df.empty:
        return []
    assert_okx_open_interest_schema(df)

    written: list[Path] = []
    df = df.copy()
    df["_year_month"] = df["timestamp"].dt.strftime("%Y-%m")
    for (inst_id, year_month), group in df.groupby(["inst_id", "_year_month"], observed=True):
        path = _okx_open_interest_partition_dir(data_dir, str(inst_id), str(year_month))
        _write_merged(group.drop(columns="_year_month"), path, ["timestamp", "inst_id"])
        written.append(path)
    return written


def write_okx_long_short_ratio(df: pd.DataFrame, data_dir: Path, period: str) -> list[Path]:
    """Write an OKX long/short-ratio frame, splitting it into monthly
    partitions - same shape/behavior as `write_okx_open_interest`, plus a
    `period` dimension since this endpoint does support multiple
    aggregation windows.
    """
    if df.empty:
        return []
    assert_okx_long_short_ratio_schema(df)

    written: list[Path] = []
    df = df.copy()
    df["_year_month"] = df["timestamp"].dt.strftime("%Y-%m")
    for (inst_id, year_month), group in df.groupby(["inst_id", "_year_month"], observed=True):
        path = _okx_long_short_ratio_partition_dir(
            data_dir, str(inst_id), period, str(year_month)
        )
        _write_merged(group.drop(columns="_year_month"), path, ["timestamp", "inst_id"])
        written.append(path)
    return written


def read_okx_open_interest(
    data_dir: Path,
    inst_id: str,
    start: pd.Timestamp | None = None,
    end: pd.Timestamp | None = None,
) -> pd.DataFrame:
    """Read all monthly OKX open-interest partitions for `inst_id`,
    optionally sliced to [start, end].
    """
    partition_dir = Path(data_dir) / "okx_open_interest" / inst_id
    if not partition_dir.exists():
        return empty_okx_open_interest_frame()

    frames = [pd.read_parquet(p) for p in sorted(partition_dir.glob("*.parquet"))]
    if not frames:
        return empty_okx_open_interest_frame()

    df = pd.concat(frames, ignore_index=True)
    df = df.sort_values("timestamp").reset_index(drop=True)
    if start is not None:
        df = df[df["timestamp"] >= start]
    if end is not None:
        df = df[df["timestamp"] <= end]
    return df.reset_index(drop=True)


def read_okx_long_short_ratio(
    data_dir: Path,
    inst_id: str,
    period: str,
    start: pd.Timestamp | None = None,
    end: pd.Timestamp | None = None,
) -> pd.DataFrame:
    """Read all monthly OKX long/short-ratio partitions for
    `inst_id`/`period`, optionally sliced to [start, end].
    """
    partition_dir = Path(data_dir) / "okx_long_short_ratio" / inst_id / period
    if not partition_dir.exists():
        return empty_okx_long_short_ratio_frame()

    frames = [pd.read_parquet(p) for p in sorted(partition_dir.glob("*.parquet"))]
    if not frames:
        return empty_okx_long_short_ratio_frame()

    df = pd.concat(frames, ignore_index=True)
    df = df.sort_values("timestamp").reset_index(drop=True)
    if start is not None:
        df = df[df["timestamp"] >= start]
    if end is not None:
        df = df[df["timestamp"] <= end]
    return df.reset_index(drop=True)
