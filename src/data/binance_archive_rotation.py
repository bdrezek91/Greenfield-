"""Verified month rotation for capacity-bounded Binance Bronze and Silver."""

from __future__ import annotations

import json
import os
import shutil
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from src.data.binance_public_archive import sha256_file

_DATASETS = ("trades", "aggTrades")
_MARKETS = ("spot", "futures-um")
_SYMBOLS = ("BTCUSDT", "ETHUSDT", "SOLUSDT")


def rotate_binance_archive_month(
    data_dir: Path,
    backup_root: Path,
    *,
    period: str,
    execute: bool,
    prune_source: bool,
) -> dict[str, Any]:
    """Copy, checksum and optionally prune one complete Bronze/Silver month."""
    data = Path(data_dir).resolve(strict=True)
    backup = Path(backup_root).resolve()
    if data == backup or data in backup.parents or backup in data.parents:
        raise ValueError("backup root must be distinct and outside data_dir")
    files, identities = _discover_period_files(data, period)
    expected = {
        f"{market}:{dataset}:{symbol}"
        for market in _MARKETS
        for dataset in _DATASETS
        for symbol in _SYMBOLS
    }
    if identities["bronze"] != expected or identities["silver"] != expected:
        raise ValueError(
            "rotation requires complete Bronze and Silver trades/aggTrades "
            f"for all BTC/ETH/SOL spot/perp streams: {period}"
        )
    if len(files) != 48:
        raise ValueError(f"rotation requires exactly 48 source files; found {len(files)}")
    entries = [
        {
            "path": path.relative_to(data).as_posix(),
            "size_bytes": path.stat().st_size,
            "sha256": sha256_file(path),
        }
        for path in sorted(files)
    ]
    total_bytes = sum(path.stat().st_size for path in files)
    report: dict[str, Any] = {
        "schema_version": 1,
        "period": period,
        "source_root": str(data),
        "backup_root": str(backup),
        "file_count": len(entries),
        "total_bytes": total_bytes,
        "files": entries,
        "executed": execute,
        "source_pruned": False,
        "qualified": False,
    }
    if not execute:
        return report
    capacity_root = _existing_parent(backup)
    if shutil.disk_usage(capacity_root).free < total_bytes + 1024**3:
        raise OSError("backup volume lacks source bytes plus 1 GiB safety margin")
    destination_root = backup / period
    for entry in entries:
        source = data / str(entry["path"])
        destination = destination_root / str(entry["path"])
        _copy_verified(source, destination, expected_sha256=str(entry["sha256"]))
    report["qualified"] = all(
        sha256_file(destination_root / str(entry["path"])) == entry["sha256"]
        for entry in entries
    )
    if not report["qualified"]:
        raise ValueError("rotated Binance backup failed checksum verification")
    report["completed_at_utc"] = datetime.now(UTC).isoformat()
    manifest_path = destination_root / "rotation-manifest.json"
    _write_json_atomic(manifest_path, report)
    if prune_source:
        for entry in entries:
            (data / str(entry["path"])).unlink()
        report["source_pruned"] = True
        _write_json_atomic(destination_root / "prune-evidence.json", report)
    return report


def _discover_period_files(
    data_dir: Path, period: str
) -> tuple[set[Path], dict[str, set[str]]]:
    files: set[Path] = set()
    identities: dict[str, set[str]] = {"bronze": set(), "silver": set()}
    bronze = data_dir / "external" / "binance-public-data"
    for manifest in bronze.rglob("*.zip.manifest.json") if bronze.exists() else ():
        raw = json.loads(manifest.read_text(encoding="utf-8"))
        fields = str(raw.get("identity", "")).split(":")
        if len(fields) != 6:
            continue
        market, _, dataset, symbol, _, source_period = fields
        normalized_market = market.replace("/", "-")
        if source_period != period or dataset not in _DATASETS:
            continue
        source = Path(str(manifest).removesuffix(".manifest.json"))
        if not source.exists():
            raise FileNotFoundError(f"Bronze source missing: {source}")
        identities["bronze"].add(f"{normalized_market}:{dataset}:{symbol}")
        files.update((source, manifest))
    silver = data_dir / "silver" / "binance-public-data" / "v1"
    for manifest in silver.rglob("part.manifest.json") if silver.exists() else ():
        raw = json.loads(manifest.read_text(encoding="utf-8"))
        dataset = str(raw.get("dataset", ""))
        if str(raw.get("period", "")) != period or dataset not in _DATASETS:
            continue
        market = str(raw.get("market", ""))
        symbol = str(raw.get("symbol", ""))
        source = manifest.with_name("part.parquet")
        if not source.exists():
            raise FileNotFoundError(f"Silver source missing: {source}")
        identities["silver"].add(f"{market}:{dataset}:{symbol}")
        files.update((source, manifest))
    return files, identities


def _copy_verified(source: Path, destination: Path, *, expected_sha256: str) -> None:
    if destination.exists():
        if sha256_file(destination) != expected_sha256:
            raise ValueError(f"existing backup checksum mismatch: {destination}")
        return
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_suffix(destination.suffix + ".part")
    try:
        with source.open("rb") as input_stream, temporary.open("xb") as output_stream:
            shutil.copyfileobj(input_stream, output_stream, length=4 * 1024 * 1024)
            output_stream.flush()
            os.fsync(output_stream.fileno())
        if sha256_file(temporary) != expected_sha256:
            raise ValueError(f"backup copy checksum mismatch: {destination}")
        temporary.replace(destination)
    finally:
        temporary.unlink(missing_ok=True)


def _existing_parent(path: Path) -> Path:
    value = path
    while not value.exists():
        if value.parent == value:
            raise FileNotFoundError(f"no existing parent for backup root: {path}")
        value = value.parent
    return value


def _write_json_atomic(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".part")
    try:
        with temporary.open("w", encoding="utf-8", newline="\n") as stream:
            json.dump(value, stream, indent=2, sort_keys=True)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)
