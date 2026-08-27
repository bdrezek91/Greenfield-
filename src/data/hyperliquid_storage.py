"""Parquet storage for Hyperliquid research market data - the Hyperliquid
counterpart to src/data/okx_derivatives_storage.py. Same monthly-partition,
atomic-merge-and-dedup shape; separate `hyperliquid_*` top-level
directories so a Hyperliquid `coin` (e.g. "BTC") can never collide with
another venue's symbol string.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from src.data.atomic_parquet import merge_atomic_parquet
from src.data.schema_hyperliquid import (
    assert_hyperliquid_asset_context_schema,
    assert_hyperliquid_bbo_schema,
    assert_hyperliquid_funding_history_schema,
    assert_hyperliquid_predicted_funding_schema,
    empty_hyperliquid_asset_context_frame,
    empty_hyperliquid_bbo_frame,
    empty_hyperliquid_funding_history_frame,
    empty_hyperliquid_predicted_funding_frame,
)

_DATASETS: dict[str, tuple[str, list[str]]] = {
    "asset_ctx": ("hyperliquid_asset_ctx", ["timestamp", "coin"]),
    "funding_history": ("hyperliquid_funding_history", ["timestamp", "coin"]),
    "predicted_funding": ("hyperliquid_predicted_funding", ["timestamp", "coin", "venue"]),
    "bbo": ("hyperliquid_bbo", ["timestamp", "coin"]),
}


def _partition_path(data_dir: Path, dataset: str, coin: str, year_month: str) -> Path:
    directory, _ = _DATASETS[dataset]
    return Path(data_dir) / directory / coin / f"{year_month}.parquet"


def _write(df: pd.DataFrame, data_dir: Path, dataset: str) -> list[Path]:
    if df.empty:
        return []
    _, dedup_subset = _DATASETS[dataset]
    written: list[Path] = []
    df = df.copy()
    df["_year_month"] = df["timestamp"].dt.strftime("%Y-%m")
    for (coin, year_month), group in df.groupby(["coin", "_year_month"], observed=True):
        path = _partition_path(data_dir, dataset, str(coin), str(year_month))
        merge_atomic_parquet(
            path,
            group.drop(columns="_year_month"),
            deduplicate_on=tuple(dedup_subset),
            sort_by=("timestamp",),
        )
        written.append(path)
    return written


def _read(data_dir: Path, dataset: str, coin: str, empty_frame: pd.DataFrame) -> pd.DataFrame:
    directory, _ = _DATASETS[dataset]
    partition_dir = Path(data_dir) / directory / coin
    if not partition_dir.exists():
        return empty_frame
    frames = [pd.read_parquet(p) for p in sorted(partition_dir.glob("*.parquet"))]
    if not frames:
        return empty_frame
    df = pd.concat(frames, ignore_index=True)
    return df.sort_values("timestamp").reset_index(drop=True)


def write_hyperliquid_asset_ctx(df: pd.DataFrame, data_dir: Path) -> list[Path]:
    if not df.empty:
        assert_hyperliquid_asset_context_schema(df)
    return _write(df, data_dir, "asset_ctx")


def read_hyperliquid_asset_ctx(data_dir: Path, coin: str) -> pd.DataFrame:
    return _read(data_dir, "asset_ctx", coin, empty_hyperliquid_asset_context_frame())


def write_hyperliquid_funding_history(df: pd.DataFrame, data_dir: Path) -> list[Path]:
    if not df.empty:
        assert_hyperliquid_funding_history_schema(df)
    return _write(df, data_dir, "funding_history")


def read_hyperliquid_funding_history(data_dir: Path, coin: str) -> pd.DataFrame:
    return _read(data_dir, "funding_history", coin, empty_hyperliquid_funding_history_frame())


def write_hyperliquid_predicted_funding(df: pd.DataFrame, data_dir: Path) -> list[Path]:
    if not df.empty:
        assert_hyperliquid_predicted_funding_schema(df)
    return _write(df, data_dir, "predicted_funding")


def read_hyperliquid_predicted_funding(data_dir: Path, coin: str) -> pd.DataFrame:
    return _read(data_dir, "predicted_funding", coin, empty_hyperliquid_predicted_funding_frame())


def write_hyperliquid_bbo(df: pd.DataFrame, data_dir: Path) -> list[Path]:
    if not df.empty:
        assert_hyperliquid_bbo_schema(df)
    return _write(df, data_dir, "bbo")


def read_hyperliquid_bbo(data_dir: Path, coin: str) -> pd.DataFrame:
    return _read(data_dir, "bbo", coin, empty_hyperliquid_bbo_frame())
