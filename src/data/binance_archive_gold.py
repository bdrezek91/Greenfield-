"""Materialize historical Binance trade Silver into versioned Gold features."""

from __future__ import annotations

import json
import os
import shutil
from calendar import monthrange
from collections.abc import Callable
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

import pandas as pd

from src.data.binance_public_archive import sha256_file
from src.features.binance_archive_flow import (
    archive_footprint,
    archive_mc_like_features,
    archive_trade_bars,
    archive_volume_profile,
    stitch_archive_cvd,
    synchronize_spot_perp_flow,
)


def materialize_binance_archive_gold(
    *,
    data_dir: Path,
    symbol: str,
    period: str,
    price_tick: float,
    frequency: str = "1min",
    dataset: str = "trades",
    day: date | None = None,
    minimum_free_bytes: int,
    disk_usage: Callable[[Path], Any] = shutil.disk_usage,
) -> tuple[Path, bool, dict[str, Any]]:
    """Build bars, footprint/profile, MC-like, and synchronized spot-perp Gold."""
    if symbol not in {"BTCUSDT", "ETHUSDT", "SOLUSDT"}:
        raise ValueError("unsupported Binance Gold symbol")
    if dataset not in {"trades", "aggTrades"}:
        raise ValueError("unsupported Binance Gold trade dataset")
    if day is not None and day.strftime("%Y-%m") != period:
        raise ValueError("Binance Gold day must belong to period")
    root = Path(data_dir)
    source_paths = {
        market: root.joinpath(
            "silver",
            "binance-public-data",
            "v1",
            f"market={market}",
            f"dataset={dataset}",
            f"symbol={symbol}",
            f"period={period}",
            "part.parquet",
        )
        for market in ("spot", "futures-um")
    }
    for source in source_paths.values():
        if not source.exists() or not source.with_suffix(".manifest.json").exists():
            raise FileNotFoundError(f"missing normalized Binance Silver input: {source}")
    sources = {market: sha256_file(path) for market, path in source_paths.items()}
    output_dir = root.joinpath(
        "gold",
        "binance-public-data",
        "v1",
        f"frequency={frequency}",
        f"dataset={dataset}",
        f"symbol={symbol}",
        f"period={period}",
        *([f"date={day.isoformat()}"] if day is not None else []),
    )
    manifest_path = output_dir / "manifest.json"
    parameters = {
        "symbol": symbol,
        "period": period,
        "dataset": dataset,
        "frequency": frequency,
        "price_tick": price_tick,
        "day": day.isoformat() if day is not None else None,
        "cvd_scope": "day" if day is not None else "period",
        "clock_join": "exact_inner",
    }
    if manifest_path.exists():
        existing = json.loads(manifest_path.read_text(encoding="utf-8"))
        if existing.get("source_sha256") == sources and existing.get(
            "parameters"
        ) == parameters and _outputs_match(output_dir, existing):
            return output_dir, False, existing
        raise ValueError(f"existing Binance Gold evidence mismatch: {output_dir}")
    output_dir.mkdir(parents=True, exist_ok=True)
    if int(disk_usage(output_dir).free) < minimum_free_bytes:
        raise OSError("Binance Gold free-space reserve breached")
    frames: dict[str, pd.DataFrame] = {}
    outputs: dict[str, dict[str, Any]] = {}
    for market, source in source_paths.items():
        filters = None
        if day is not None:
            start = pd.Timestamp(day, tz="UTC")
            end = pd.Timestamp(day + timedelta(days=1), tz="UTC")
            filters = [("timestamp", ">=", start), ("timestamp", "<", end)]
        trades = pd.read_parquet(
            source,
            columns=[
                "timestamp",
                "exchange",
                "market",
                "dataset",
                "symbol",
                "trade_id",
                "price",
                "quantity",
                "quote_quantity",
                "signed_quantity",
            ],
            filters=filters,
        )
        bars = archive_trade_bars(trades, frequency=frequency)
        footprint = archive_footprint(
            trades,
            price_tick=price_tick,
            frequency=frequency,
        )
        profile = archive_volume_profile(footprint)
        mc_like = archive_mc_like_features(bars)
        frames[market] = bars
        prefix = market.replace("-", "_")
        for name, frame in (
            (f"{prefix}_bars", bars),
            (f"{prefix}_footprint", footprint),
            (f"{prefix}_volume_profile", profile),
            (f"{prefix}_mc_like", mc_like),
        ):
            outputs[name] = _write_frame_atomic(
                output_dir / f"{name}.parquet",
                frame,
                minimum_free_bytes=minimum_free_bytes,
                disk_usage=disk_usage,
            )
    synchronized = synchronize_spot_perp_flow(
        pd.concat([frames["spot"], frames["futures-um"]], ignore_index=True)
    )
    outputs["spot_perp_flow"] = _write_frame_atomic(
        output_dir / "spot_perp_flow.parquet",
        synchronized,
        minimum_free_bytes=minimum_free_bytes,
        disk_usage=disk_usage,
    )
    metadata: dict[str, Any] = {
        "schema_version": 1,
        "source_sha256": sources,
        "parameters": parameters,
        "outputs": outputs,
        "materialized_at_utc": datetime.now(UTC).isoformat(),
    }
    _write_json_atomic(manifest_path, metadata)
    return output_dir, True, metadata


def finalize_binance_archive_gold_period(
    *,
    data_dir: Path,
    symbol: str,
    period: str,
    frequency: str = "1min",
    dataset: str = "trades",
    minimum_free_bytes: int,
    disk_usage: Callable[[Path], Any] = shutil.disk_usage,
) -> tuple[Path, bool, dict[str, Any]]:
    """Stitch complete daily Gold bars into continuous period features."""
    year, month = (int(value) for value in period.split("-", maxsplit=1))
    days = [
        date(year, month, value)
        for value in range(1, monthrange(year, month)[1] + 1)
    ]
    base = Path(data_dir).joinpath(
        "gold",
        "binance-public-data",
        "v1",
        f"frequency={frequency}",
        f"dataset={dataset}",
        f"symbol={symbol}",
        f"period={period}",
    )
    daily_manifests: dict[str, str] = {}
    daily_bars: dict[str, dict[str, pd.DataFrame]] = {
        "spot": {},
        "futures-um": {},
    }
    price_tick: float | None = None
    for day in days:
        day_key = day.isoformat()
        day_dir = base / f"date={day_key}"
        manifest_path = day_dir / "manifest.json"
        if not manifest_path.exists():
            raise FileNotFoundError(f"missing daily Binance Gold manifest: {manifest_path}")
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        parameters = manifest.get("parameters")
        if not isinstance(parameters, dict) or any(
            parameters.get(key) != expected
            for key, expected in {
                "symbol": symbol,
                "period": period,
                "dataset": dataset,
                "frequency": frequency,
                "day": day_key,
                "cvd_scope": "day",
            }.items()
        ):
            raise ValueError(f"daily Binance Gold identity mismatch: {manifest_path}")
        current_tick = float(parameters["price_tick"])
        if price_tick is None:
            price_tick = current_tick
        elif current_tick != price_tick:
            raise ValueError("daily Binance Gold price_tick changed within period")
        if not _outputs_match(day_dir, manifest):
            raise ValueError(f"daily Binance Gold output evidence mismatch: {manifest_path}")
        daily_manifests[day_key] = sha256_file(manifest_path)
        daily_outputs = manifest["outputs"]
        for market, output_name in (
            ("spot", "spot_bars"),
            ("futures-um", "futures_um_bars"),
        ):
            evidence = daily_outputs.get(output_name)
            if not isinstance(evidence, dict):
                raise ValueError(f"daily Binance Gold bars missing: {manifest_path}")
            daily_bars[market][day_key] = pd.read_parquet(Path(evidence["path"]))
    output_dir = base / "scope=continuous-period"
    manifest_path = output_dir / "manifest.json"
    parameters = {
        "symbol": symbol,
        "period": period,
        "dataset": dataset,
        "frequency": frequency,
        "price_tick": price_tick,
        "day": None,
        "cvd_scope": "continuous_period",
        "mc_like_scope": "continuous_period",
        "clock_join": "exact_inner",
    }
    if manifest_path.exists():
        existing = json.loads(manifest_path.read_text(encoding="utf-8"))
        if existing.get("source_manifest_sha256") == daily_manifests and existing.get(
            "parameters"
        ) == parameters and _outputs_match(output_dir, existing):
            return output_dir, False, existing
        raise ValueError(f"existing continuous Binance Gold evidence mismatch: {output_dir}")
    output_dir.mkdir(parents=True, exist_ok=True)
    outputs: dict[str, dict[str, Any]] = {}
    continuous: dict[str, pd.DataFrame] = {}
    for market in ("spot", "futures-um"):
        bars = stitch_archive_cvd(daily_bars[market])
        continuous[market] = bars
        prefix = market.replace("-", "_")
        outputs[f"{prefix}_bars"] = _write_frame_atomic(
            output_dir / f"{prefix}_bars.parquet",
            bars,
            minimum_free_bytes=minimum_free_bytes,
            disk_usage=disk_usage,
        )
        outputs[f"{prefix}_mc_like"] = _write_frame_atomic(
            output_dir / f"{prefix}_mc_like.parquet",
            archive_mc_like_features(bars),
            minimum_free_bytes=minimum_free_bytes,
            disk_usage=disk_usage,
        )
    synchronized = synchronize_spot_perp_flow(
        pd.concat([continuous["spot"], continuous["futures-um"]], ignore_index=True)
    )
    outputs["spot_perp_flow"] = _write_frame_atomic(
        output_dir / "spot_perp_flow.parquet",
        synchronized,
        minimum_free_bytes=minimum_free_bytes,
        disk_usage=disk_usage,
    )
    metadata: dict[str, Any] = {
        "schema_version": 1,
        "source_manifest_sha256": daily_manifests,
        "parameters": parameters,
        "outputs": outputs,
        "materialized_at_utc": datetime.now(UTC).isoformat(),
    }
    _write_json_atomic(manifest_path, metadata)
    return output_dir, True, metadata


def _write_frame_atomic(
    path: Path,
    frame: pd.DataFrame,
    *,
    minimum_free_bytes: int,
    disk_usage: Callable[[Path], Any],
) -> dict[str, Any]:
    if frame.empty:
        raise ValueError(f"refusing to publish empty Binance Gold output: {path.name}")
    if int(disk_usage(path.parent).free) < minimum_free_bytes:
        raise OSError("Binance Gold free-space reserve breached")
    temp = path.with_suffix(".parquet.part")
    try:
        frame.to_parquet(temp, index=False, compression="zstd")
        with temp.open("rb+") as value:
            os.fsync(value.fileno())
        temp.replace(path)
    finally:
        temp.unlink(missing_ok=True)
    return {"path": str(path), "sha256": sha256_file(path), "row_count": len(frame)}


def _outputs_match(output_dir: Path, manifest: dict[str, Any]) -> bool:
    outputs = manifest.get("outputs")
    if not isinstance(outputs, dict) or not outputs:
        return False
    for evidence in outputs.values():
        if not isinstance(evidence, dict):
            return False
        path = Path(str(evidence.get("path", "")))
        if path.parent != output_dir or not path.exists():
            return False
        if evidence.get("sha256") != sha256_file(path):
            return False
    return True


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
