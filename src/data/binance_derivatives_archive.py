"""Normalize Binance reference-price klines and derivatives metrics to Silver."""

from __future__ import annotations

import json
import math
import os
import shutil
import zipfile
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pandas as pd

from src.data.binance_public_archive import sha256_file

_SYMBOLS = {"BTCUSDT", "ETHUSDT", "SOLUSDT"}
_KLINE_DATASETS = {"markPriceKlines", "indexPriceKlines", "premiumIndexKlines"}
_KLINE_COLUMNS = [
    "open_time", "open", "high", "low", "close", "volume", "close_time",
    "quote_volume", "count", "taker_buy_volume", "taker_buy_quote_volume", "ignore",
]
_METRIC_COLUMNS = [
    "create_time", "symbol", "sum_open_interest", "sum_open_interest_value",
    "count_toptrader_long_short_ratio", "sum_toptrader_long_short_ratio",
    "count_long_short_ratio", "sum_taker_long_short_vol_ratio",
]


def normalize_binance_derivatives_archive(
    source: Path,
    *,
    data_dir: Path,
    minimum_free_bytes: int,
    disk_usage: Callable[[Path], Any] = shutil.disk_usage,
) -> tuple[Path, bool, dict[str, Any]]:
    """Normalize one manifest-bound Binance reference-price or metrics ZIP."""
    source = Path(source)
    identity = _identity(source)
    output = Path(data_dir).joinpath(
        "silver", "binance-public-data", "v1", "market=futures-um",
        f"dataset={identity['dataset']}", f"symbol={identity['symbol']}",
        f"period={identity['period']}", "part.parquet",
    )
    manifest_path = output.with_suffix(".manifest.json")
    source_sha256 = sha256_file(source)
    if output.exists() and manifest_path.exists():
        existing = json.loads(manifest_path.read_text(encoding="utf-8"))
        if existing.get("source_sha256") == source_sha256 and existing.get(
            "output_sha256"
        ) == sha256_file(output):
            return output, False, existing
        raise ValueError(f"existing normalized derivatives evidence mismatch: {output}")
    raw = _read_single_csv(source)
    frame = (
        _normalize_kline(raw, identity)
        if identity["dataset"] in _KLINE_DATASETS
        else _normalize_metrics(raw, identity)
    )
    _validate_frame(frame)
    output.parent.mkdir(parents=True, exist_ok=True)
    if int(disk_usage(output.parent).free) < minimum_free_bytes:
        raise OSError("derivatives normalization free-space reserve breached")
    temp = output.with_suffix(".parquet.part")
    try:
        frame.to_parquet(temp, index=False, compression="zstd")
        with temp.open("rb+") as value:
            os.fsync(value.fileno())
        temp.replace(output)
    finally:
        temp.unlink(missing_ok=True)
    metadata: dict[str, Any] = {
        "schema_version": 1,
        "exchange": "binance",
        "market": "futures-um",
        **identity,
        "source_path": str(source),
        "source_sha256": source_sha256,
        "output_path": str(output),
        "output_sha256": sha256_file(output),
        "row_count": len(frame),
        "min_timestamp_utc": frame["timestamp"].min().isoformat(),
        "max_timestamp_utc": frame["timestamp"].max().isoformat(),
        "normalized_at_utc": datetime.now(UTC).isoformat(),
    }
    _write_json_atomic(manifest_path, metadata)
    return output, True, metadata


def _identity(source: Path) -> dict[str, str]:
    raw = json.loads(
        source.with_suffix(source.suffix + ".manifest.json").read_text(encoding="utf-8")
    )
    fields = str(raw.get("identity", "")).split(":")
    if len(fields) != 6:
        raise ValueError("invalid Binance derivatives archive identity")
    market, cadence, dataset, symbol, interval, period = fields
    valid_kline = dataset in _KLINE_DATASETS and cadence == "monthly" and interval == "1m"
    valid_metrics = dataset == "metrics" and cadence == "daily" and interval == "none"
    if market != "futures/um" or symbol not in _SYMBOLS or not (valid_kline or valid_metrics):
        raise ValueError("unexpected Binance derivatives archive identity")
    return {"dataset": dataset, "symbol": symbol, "period": period, "interval": interval}


def _read_single_csv(source: Path) -> pd.DataFrame:
    with zipfile.ZipFile(source) as archive:
        members = [name for name in archive.namelist() if name.lower().endswith(".csv")]
        if len(members) != 1:
            raise ValueError("Binance derivatives archive must contain exactly one CSV")
        with archive.open(members[0]) as csv_file:
            return pd.read_csv(csv_file, dtype=str)


def _normalize_kline(raw: pd.DataFrame, identity: dict[str, str]) -> pd.DataFrame:
    if list(raw.columns) != _KLINE_COLUMNS:
        raise ValueError(f"unexpected Binance kline columns: {list(raw.columns)}")
    numeric = raw[_KLINE_COLUMNS].apply(pd.to_numeric, errors="raise")
    return pd.DataFrame(
        {
            "timestamp": pd.to_datetime(numeric["open_time"].astype("int64"), unit="ms", utc=True),
            "close_timestamp": pd.to_datetime(
                numeric["close_time"].astype("int64"), unit="ms", utc=True
            ),
            "exchange": "binance",
            "market": "futures-um",
            "dataset": identity["dataset"],
            "symbol": identity["symbol"],
            "open": numeric["open"].astype("float64"),
            "high": numeric["high"].astype("float64"),
            "low": numeric["low"].astype("float64"),
            "close": numeric["close"].astype("float64"),
            "sample_count": numeric["count"].astype("int64"),
        }
    )


def _normalize_metrics(raw: pd.DataFrame, identity: dict[str, str]) -> pd.DataFrame:
    if list(raw.columns) != _METRIC_COLUMNS:
        raise ValueError(f"unexpected Binance metrics columns: {list(raw.columns)}")
    if set(raw["symbol"].astype(str)) != {identity["symbol"]}:
        raise ValueError("Binance metrics symbol does not match manifest")
    numeric_columns = _METRIC_COLUMNS[2:]
    numeric = raw[numeric_columns].apply(pd.to_numeric, errors="raise").astype("float64")
    frame = pd.DataFrame(
        {
            "timestamp": pd.to_datetime(raw["create_time"], utc=True, errors="raise"),
            "exchange": "binance",
            "market": "futures-um",
            "dataset": "metrics",
            "symbol": identity["symbol"],
            **{column: numeric[column] for column in numeric_columns},
        }
    )
    if frame["timestamp"].duplicated().any():
        raise ValueError("Binance metrics archive contains duplicate timestamps")
    return frame.sort_values("timestamp", kind="stable").reset_index(drop=True)


def _validate_frame(frame: pd.DataFrame) -> None:
    if frame.empty:
        raise ValueError("Binance derivatives archive is empty")
    if not frame["timestamp"].is_monotonic_increasing or frame["timestamp"].duplicated().any():
        raise ValueError("derivatives timestamps must be strictly increasing")
    numeric = frame.select_dtypes(include="number")
    if not numeric.map(lambda value: math.isfinite(float(value))).all().all():
        raise ValueError("derivatives archive contains non-finite values")
    if "close_timestamp" in frame and (frame["close_timestamp"] < frame["timestamp"]).any():
        raise ValueError("kline close timestamp precedes open timestamp")


def _write_json_atomic(path: Path, value: dict[str, Any]) -> None:
    temp = path.with_suffix(path.suffix + ".part")
    try:
        with temp.open("w", encoding="utf-8") as stream:
            json.dump(value, stream, indent=2, sort_keys=True)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        temp.replace(path)
    finally:
        temp.unlink(missing_ok=True)
