"""Parquet storage for Binance klines - the Binance counterpart to the
kline half of src/data/storage.py.

Separate module, separate top-level directory (`binance_klines/`) for the
same reason as every other Cycle 17+ per-exchange module: `storage.py`'s
bare `klines/<symbol>/<timeframe>/...` path has no exchange dimension, so
writing Binance's BTCUSDT there would collide with Bybit's identically-
named, differently-priced BTCUSDT klines - the exact same risk this
project has consistently avoided since Cycle 17 (see
src/data/binance_derivatives_storage.py's module docstring for the first,
more detailed statement of this). Reuses src/data/schema.py's
COLUMNS/assert_schema/empty_klines_frame unchanged - the canonical OHLCV
shape has no exchange field either, so there is nothing exchange-specific
to add there; only the storage PATH differs.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from src.data.atomic_parquet import merge_atomic_parquet
from src.data.schema import assert_schema, empty_klines_frame


def _partition_dir(data_dir: Path, symbol: str, timeframe: str, year_month: str) -> Path:
    return Path(data_dir) / "binance_klines" / symbol / timeframe / f"{year_month}.parquet"


def write_binance_klines(df: pd.DataFrame, data_dir: Path) -> list[Path]:
    """Write a Binance klines frame, splitting it into monthly partitions -
    same merge-not-overwrite behavior as src/data/storage.py::write_klines.
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
        group = group.drop(columns="_year_month")
        merge_atomic_parquet(
            path, group,
            deduplicate_on=("timestamp", "symbol", "timeframe"),
            sort_by=("timestamp",),
        )
        written.append(path)
    return written


def read_binance_klines(
    data_dir: Path,
    symbol: str,
    timeframe: str,
    start: pd.Timestamp | None = None,
    end: pd.Timestamp | None = None,
) -> pd.DataFrame:
    """Read all monthly Binance kline partitions for `symbol`/`timeframe`,
    optionally sliced to [start, end] - same signature/behavior as
    src/data/storage.py::read_klines.
    """
    partition_dir = Path(data_dir) / "binance_klines" / symbol / timeframe
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
