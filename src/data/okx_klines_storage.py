"""Parquet storage for OKX klines - the OKX counterpart to
src/data/binance_klines_storage.py.

Separate module, separate top-level directory (`okx_klines/`) for the
same reason as Binance's: `storage.py`'s bare `klines/<symbol>/...` path
has no exchange dimension, and OKX's instId strings (e.g.
"BTC-USDT-SWAP") could otherwise collide in spirit with Binance/Bybit
data if ever normalized to a bare "BTCUSDT"-style key. Reuses
src/data/schema.py's COLUMNS/assert_schema/empty_klines_frame unchanged.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from src.data.atomic_parquet import merge_atomic_parquet
from src.data.schema import assert_schema, empty_klines_frame


def _partition_dir(data_dir: Path, inst_id: str, timeframe: str, year_month: str) -> Path:
    return Path(data_dir) / "okx_klines" / inst_id / timeframe / f"{year_month}.parquet"


def write_okx_klines(df: pd.DataFrame, data_dir: Path) -> list[Path]:
    """Write an OKX klines frame, splitting it into monthly partitions -
    same merge-not-overwrite behavior as src/data/storage.py::write_klines.
    """
    if df.empty:
        return []
    assert_schema(df)

    written: list[Path] = []
    df = df.copy()
    df["_year_month"] = df["timestamp"].dt.strftime("%Y-%m")
    for (inst_id, timeframe, year_month), group in df.groupby(
        ["symbol", "timeframe", "_year_month"], observed=True
    ):
        path = _partition_dir(data_dir, str(inst_id), str(timeframe), str(year_month))
        group = group.drop(columns="_year_month")
        merge_atomic_parquet(
            path, group,
            deduplicate_on=("timestamp", "symbol", "timeframe"),
            sort_by=("timestamp",),
        )
        written.append(path)
    return written


def read_okx_klines(
    data_dir: Path,
    inst_id: str,
    timeframe: str,
    start: pd.Timestamp | None = None,
    end: pd.Timestamp | None = None,
) -> pd.DataFrame:
    """Read all monthly OKX kline partitions for `inst_id`/`timeframe`,
    optionally sliced to [start, end] - same signature/behavior as
    src/data/storage.py::read_klines.
    """
    partition_dir = Path(data_dir) / "okx_klines" / inst_id / timeframe
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
