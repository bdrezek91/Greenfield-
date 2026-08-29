"""Fail-closed quality and lineage gate for one closed Binance archive month."""

from __future__ import annotations

import json
from calendar import monthrange
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import pyarrow.parquet as pq

from src.data.binance_public_archive import sha256_file
from src.data.binance_trade_archive import TRADE_SCHEMA

_MARKETS = ("spot", "futures-um")
_SYMBOLS = ("BTCUSDT", "ETHUSDT", "SOLUSDT")


def audit_binance_archive_month(
    data_dir: Path,
    *,
    period: str,
    dataset: str = "trades",
    frequency: str = "1min",
) -> dict[str, Any]:
    """Verify complete Silver and continuous Gold evidence without loading it all."""
    if dataset not in {"trades", "aggTrades"}:
        raise ValueError("dataset must be trades or aggTrades")
    start = pd.Timestamp(f"{period}-01", tz="UTC")
    end = start + pd.offsets.MonthBegin(1)
    silver = [
        _audit_silver_part(
            Path(data_dir),
            market=market,
            dataset=dataset,
            symbol=symbol,
            period=period,
            start=start,
            end=end,
        )
        for market in _MARKETS
        for symbol in _SYMBOLS
    ]
    gold = [
        _audit_continuous_gold(
            Path(data_dir),
            symbol=symbol,
            period=period,
            dataset=dataset,
            frequency=frequency,
        )
        for symbol in _SYMBOLS
    ]
    qualified = all(item["qualified"] for item in (*silver, *gold))
    return {
        "schema_version": 1,
        "observed_at_utc": datetime.now(UTC).isoformat(),
        "period": period,
        "dataset": dataset,
        "frequency": frequency,
        "qualified": qualified,
        "oos_ready": qualified,
        "silver": silver,
        "gold": gold,
    }


def _audit_silver_part(
    data_dir: Path,
    *,
    market: str,
    dataset: str,
    symbol: str,
    period: str,
    start: pd.Timestamp,
    end: pd.Timestamp,
) -> dict[str, Any]:
    output = data_dir.joinpath(
        "silver",
        "binance-public-data",
        "v1",
        f"market={market}",
        f"dataset={dataset}",
        f"symbol={symbol}",
        f"period={period}",
        "part.parquet",
    )
    manifest_path = output.with_suffix(".manifest.json")
    checks: dict[str, bool] = {}
    details: dict[str, Any] = {}
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        expected_identity = {
            "exchange": "binance",
            "market": market,
            "dataset": dataset,
            "symbol": symbol,
            "period": period,
        }
        checks["manifest_identity"] = all(
            manifest.get(key) == value for key, value in expected_identity.items()
        )
        source = Path(str(manifest["source_path"]))
        bronze_manifest = json.loads(
            source.with_suffix(source.suffix + ".manifest.json").read_text(encoding="utf-8")
        )
        source_hash = sha256_file(source)
        checks["bronze_checksum"] = (
            source_hash == manifest.get("source_sha256")
            and source_hash == bronze_manifest.get("content_sha256")
        )
        checks["silver_checksum"] = sha256_file(output) == manifest.get("output_sha256")
        parquet = pq.ParquetFile(output)
        checks["schema"] = parquet.schema_arrow.equals(TRADE_SCHEMA)
        checks["row_count"] = parquet.metadata.num_rows == int(manifest.get("row_count", -1)) > 0

        previous: tuple[pd.Timestamp, int] | None = None
        rows = 0
        min_timestamp: pd.Timestamp | None = None
        max_timestamp: pd.Timestamp | None = None
        content_valid = True
        ordered = True
        for batch in parquet.iter_batches(
            columns=[
                "timestamp",
                "exchange",
                "market",
                "dataset",
                "symbol",
                "trade_id",
                "first_trade_id",
                "last_trade_id",
                "price",
                "quantity",
                "buyer_is_maker",
                "signed_quantity",
            ],
            batch_size=500_000,
        ):
            frame = batch.to_pandas()
            rows += len(frame)
            if frame.empty:
                continue
            identities = frame[["exchange", "market", "dataset", "symbol"]].drop_duplicates()
            content_valid &= len(identities) == 1 and tuple(identities.iloc[0]) == (
                "binance",
                market,
                dataset,
                symbol,
            )
            content_valid &= bool(
                np.isfinite(frame[["price", "quantity", "signed_quantity"]]).all().all()
                and (frame["price"] > 0).all()
                and (frame["quantity"] > 0).all()
            )
            expected_signed = frame["quantity"].where(
                ~frame["buyer_is_maker"], -frame["quantity"]
            )
            content_valid &= bool(np.array_equal(frame["signed_quantity"], expected_signed))
            if dataset == "aggTrades":
                content_valid &= bool(
                    frame["first_trade_id"].notna().all()
                    and frame["last_trade_id"].notna().all()
                    and (frame["first_trade_id"] <= frame["last_trade_id"]).all()
                )
            keys = list(zip(frame["timestamp"], frame["trade_id"], strict=True))
            if previous is not None and keys[0] <= previous:
                ordered = False
            if any(right <= left for left, right in zip(keys, keys[1:], strict=False)):
                ordered = False
            previous = keys[-1]
            batch_min = pd.Timestamp(frame["timestamp"].iloc[0])
            batch_max = pd.Timestamp(frame["timestamp"].iloc[-1])
            min_timestamp = batch_min if min_timestamp is None else min(min_timestamp, batch_min)
            max_timestamp = batch_max if max_timestamp is None else max(max_timestamp, batch_max)
        checks["streamed_row_count"] = rows == int(manifest.get("row_count", -1))
        checks["content_contract"] = content_valid
        checks["strict_order_no_duplicates"] = ordered
        checks["closed_period"] = (
            min_timestamp is not None
            and max_timestamp is not None
            and min_timestamp >= start
            and max_timestamp < end
            and manifest.get("min_timestamp_utc") == min_timestamp.isoformat()
            and manifest.get("max_timestamp_utc") == max_timestamp.isoformat()
        )
        details = {
            "row_count": rows,
            "min_timestamp_utc": min_timestamp.isoformat() if min_timestamp else None,
            "max_timestamp_utc": max_timestamp.isoformat() if max_timestamp else None,
        }
    except Exception as exc:  # noqa: BLE001 - failure becomes audit evidence
        checks["readable_complete_evidence"] = False
        details["error"] = str(exc)
    return {
        "identity": f"{market}:{dataset}:{symbol}:{period}",
        "qualified": bool(checks) and all(checks.values()),
        "checks": checks,
        **details,
    }


def _audit_continuous_gold(
    data_dir: Path,
    *,
    symbol: str,
    period: str,
    dataset: str,
    frequency: str,
) -> dict[str, Any]:
    root = data_dir.joinpath(
        "gold",
        "binance-public-data",
        "v1",
        f"frequency={frequency}",
        f"dataset={dataset}",
        f"symbol={symbol}",
        f"period={period}",
    )
    continuous = root / "scope=continuous-period"
    manifest_path = continuous / "manifest.json"
    checks: dict[str, bool] = {}
    details: dict[str, Any] = {}
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        parameters = manifest.get("parameters", {})
        checks["manifest_identity"] = all(
            parameters.get(key) == value
            for key, value in {
                "symbol": symbol,
                "period": period,
                "dataset": dataset,
                "frequency": frequency,
                "day": None,
                "cvd_scope": "continuous_period",
                "clock_join": "exact_inner",
            }.items()
        )
        year, month = (int(value) for value in period.split("-", maxsplit=1))
        expected_days = {
            f"{period}-{day:02d}" for day in range(1, monthrange(year, month)[1] + 1)
        }
        lineage = manifest.get("source_manifest_sha256", {})
        checks["daily_lineage_complete"] = set(lineage) == expected_days
        lineage_valid = True
        for day, expected_hash in lineage.items():
            daily = root / f"date={day}" / "manifest.json"
            lineage_valid &= daily.exists() and sha256_file(daily) == expected_hash
        checks["daily_lineage_checksums"] = lineage_valid
        outputs = manifest.get("outputs", {})
        output_valid = bool(outputs)
        output_rows: dict[str, int] = {}
        for name, evidence in outputs.items():
            path = Path(str(evidence.get("path", "")))
            actual_rows = pq.ParquetFile(path).metadata.num_rows if path.exists() else -1
            output_valid &= (
                path.parent == continuous
                and path.exists()
                and sha256_file(path) == evidence.get("sha256")
                and actual_rows == int(evidence.get("row_count", -1)) > 0
            )
            output_rows[name] = actual_rows
        checks["output_checksums_and_rows"] = output_valid
        details["output_rows"] = output_rows
    except Exception as exc:  # noqa: BLE001 - failure becomes audit evidence
        checks["readable_complete_evidence"] = False
        details["error"] = str(exc)
    return {
        "identity": f"{dataset}:{symbol}:{period}:continuous",
        "qualified": bool(checks) and all(checks.values()),
        "checks": checks,
        **details,
    }
