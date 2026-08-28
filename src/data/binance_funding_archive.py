"""Normalize checksum-verified Binance funding archives into Silver."""

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


def normalize_binance_funding_archive(
    source: Path,
    *,
    data_dir: Path,
    minimum_free_bytes: int,
    disk_usage: Callable[[Path], Any] = shutil.disk_usage,
) -> tuple[Path, bool, dict[str, Any]]:
    """Normalize one immutable monthly funding ZIP with lineage evidence."""
    source = Path(source)
    identity = _funding_identity(source)
    output = Path(data_dir).joinpath(
        "silver",
        "binance-public-data",
        "v1",
        "market=futures-um",
        "dataset=fundingRate",
        f"symbol={identity['symbol']}",
        f"period={identity['period']}",
        "part.parquet",
    )
    manifest_path = output.with_suffix(".manifest.json")
    source_sha256 = sha256_file(source)
    if output.exists() and manifest_path.exists():
        existing = json.loads(manifest_path.read_text(encoding="utf-8"))
        if existing.get("source_sha256") == source_sha256 and existing.get(
            "output_sha256"
        ) == sha256_file(output):
            return output, False, existing
        raise ValueError(f"existing normalized funding evidence mismatch: {output}")
    with zipfile.ZipFile(source) as archive:
        members = [name for name in archive.namelist() if name.lower().endswith(".csv")]
        if len(members) != 1:
            raise ValueError("Binance funding archive must contain exactly one CSV")
        with archive.open(members[0]) as csv_file:
            raw = pd.read_csv(csv_file, dtype=str)
    required = {"calc_time", "funding_interval_hours", "last_funding_rate"}
    if set(raw.columns) != required:
        raise ValueError(f"unexpected Binance funding columns: {sorted(raw.columns)}")
    timestamp = pd.to_datetime(
        pd.to_numeric(raw["calc_time"], errors="raise").astype("int64"),
        unit="ms",
        utc=True,
    )
    interval = pd.to_numeric(raw["funding_interval_hours"], errors="raise").astype("int16")
    rate = pd.to_numeric(raw["last_funding_rate"], errors="raise").astype("float64")
    frame = pd.DataFrame(
        {
            "timestamp": timestamp,
            "exchange": "binance",
            "market": "futures-um",
            "dataset": "fundingRate",
            "symbol": identity["symbol"],
            "funding_interval_hours": interval,
            "funding_rate": rate,
        }
    )
    if frame.empty or (frame["funding_interval_hours"] <= 0).any():
        raise ValueError("funding archive is empty or has a non-positive interval")
    if not frame["timestamp"].is_monotonic_increasing or frame["timestamp"].duplicated().any():
        raise ValueError("funding timestamps must be strictly increasing")
    if not frame["funding_rate"].map(float).map(math.isfinite).all():
        raise ValueError("funding archive contains non-finite rates")
    output.parent.mkdir(parents=True, exist_ok=True)
    if int(disk_usage(output.parent).free) < minimum_free_bytes:
        raise OSError("funding normalization free-space reserve breached")
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
        "dataset": "fundingRate",
        "symbol": identity["symbol"],
        "period": identity["period"],
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


def _funding_identity(source: Path) -> dict[str, str]:
    manifest = source.with_suffix(source.suffix + ".manifest.json")
    raw = json.loads(manifest.read_text(encoding="utf-8"))
    fields = str(raw.get("identity", "")).split(":")
    if len(fields) != 6:
        raise ValueError("invalid Binance funding archive identity")
    market, cadence, dataset, symbol, interval, period = fields
    if (
        market != "futures/um"
        or cadence != "monthly"
        or dataset != "fundingRate"
        or interval != "none"
        or symbol not in {"BTCUSDT", "ETHUSDT", "SOLUSDT"}
    ):
        raise ValueError("unexpected Binance funding archive identity")
    return {"symbol": symbol, "period": period}


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
