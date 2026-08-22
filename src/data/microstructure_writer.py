"""Batch writer/reader for the three microstructure streams
(src/data/microstructure_schema.py).

Order book updates can arrive tens of times per second - the
read-existing-file/concat/overwrite pattern src/data/storage.py uses for
klines (fine at ~1 write per backfill run) would make each flush slower
than the last as a day's file grows. Instead, each flush writes its own
uniquely-named file into a per-symbol/per-day directory; reads concatenate
every file in range. Nothing is ever rewritten, so flushing stays O(batch
size) regardless of how much history already exists.
"""

from __future__ import annotations

import os
import time
import uuid
from pathlib import Path

import pandas as pd

from src.data.microstructure_schema import (
    empty_liquidation_frame,
    empty_orderbook_frame,
    empty_trade_frame,
)

_STREAM_EMPTY_FRAME = {
    "orderbook": empty_orderbook_frame,
    "trades": empty_trade_frame,
    "liquidations": empty_liquidation_frame,
}


def _stream_dir(data_dir: Path, stream: str, symbol: str, date: str) -> Path:
    return Path(data_dir) / "microstructure" / stream / symbol / date


def write_batch(rows: list[dict], data_dir: Path, stream: str, symbol: str) -> Path | None:
    """Write one flush's worth of rows as a new file. Rows are grouped by
    UTC calendar date internally so a batch spanning midnight still lands
    in the correct per-day directories; returns the path written for the
    batch's largest date group (callers only need this for logging).
    """
    if stream not in _STREAM_EMPTY_FRAME:
        raise ValueError(f"unknown stream {stream!r}, expected one of {list(_STREAM_EMPTY_FRAME)}")
    if not rows:
        return None

    df = pd.DataFrame(rows)
    df["_date"] = df["timestamp"].dt.strftime("%Y-%m-%d")

    last_path: Path | None = None
    for date, group in df.groupby("_date", observed=True):
        directory = _stream_dir(data_dir, stream, symbol, str(date))
        directory.mkdir(parents=True, exist_ok=True)
        # ``time.time_ns()`` is not guaranteed to have nanosecond resolution
        # (notably on Windows), so a timestamp-only name can silently overwrite
        # a prior fast flush. UUID makes collision independent of clock
        # resolution while the fixed-width prefix preserves approximate order.
        path = directory / f"{time.time_ns():020d}-{uuid.uuid4().hex}.parquet"
        temp_path = directory / f".{path.name}.{uuid.uuid4().hex}.tmp"
        try:
            group.drop(columns="_date").reset_index(drop=True).to_parquet(
                temp_path, index=False
            )
            # Windows requires a writable descriptor for ``os.fsync``.
            with temp_path.open("rb+") as handle:
                os.fsync(handle.fileno())
            os.replace(temp_path, path)
        finally:
            temp_path.unlink(missing_ok=True)
        last_path = path

    return last_path


def read_range(
    data_dir: Path,
    stream: str,
    symbol: str,
    start: pd.Timestamp,
    end: pd.Timestamp,
) -> pd.DataFrame:
    """Read every batch file across the UTC calendar days spanned by
    [start, end], concatenated and sorted.
    """
    if stream not in _STREAM_EMPTY_FRAME:
        raise ValueError(f"unknown stream {stream!r}, expected one of {list(_STREAM_EMPTY_FRAME)}")
    empty = _STREAM_EMPTY_FRAME[stream]()

    dates = pd.date_range(start.floor("D"), end.floor("D"), freq="D", tz=start.tz)
    frames: list[pd.DataFrame] = []
    for date in dates:
        directory = _stream_dir(data_dir, stream, symbol, date.strftime("%Y-%m-%d"))
        if not directory.exists():
            continue
        frames.extend(pd.read_parquet(p) for p in sorted(directory.glob("*.parquet")))

    if not frames:
        return empty

    df = pd.concat(frames, ignore_index=True)
    df = df[(df["timestamp"] >= start) & (df["timestamp"] <= end)]
    df = df.sort_values("timestamp").reset_index(drop=True)
    return df
