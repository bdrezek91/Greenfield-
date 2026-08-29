from __future__ import annotations

import hashlib
import json
from calendar import monthrange
from pathlib import Path

import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

from src.data.binance_archive_quality import audit_binance_archive_month
from src.data.binance_trade_archive import TRADE_SCHEMA


def _write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value), encoding="utf-8")


def _seed_month(data_dir: Path, *, corrupt_one_output: bool = False) -> None:
    period = "2026-07"
    timestamp = pd.Timestamp("2026-07-01T00:00:00Z")
    for market in ("spot", "futures-um"):
        for index, symbol in enumerate(("BTCUSDT", "ETHUSDT", "SOLUSDT"), start=1):
            source = data_dir.joinpath(
                "external",
                "binance-public-data",
                market,
                "trades",
                symbol,
                f"{symbol}-trades-{period}.zip",
            )
            source.parent.mkdir(parents=True, exist_ok=True)
            source.write_bytes(f"{market}:{symbol}".encode())
            source_hash = hashlib.sha256(source.read_bytes()).hexdigest()
            _write_json(
                source.with_suffix(".zip.manifest.json"),
                {"content_sha256": source_hash},
            )
            output = data_dir.joinpath(
                "silver",
                "binance-public-data",
                "v1",
                f"market={market}",
                "dataset=trades",
                f"symbol={symbol}",
                f"period={period}",
                "part.parquet",
            )
            output.parent.mkdir(parents=True, exist_ok=True)
            frame = pd.DataFrame(
                {
                    "timestamp": [timestamp],
                    "exchange": ["binance"],
                    "market": [market],
                    "dataset": ["trades"],
                    "symbol": [symbol],
                    "trade_id": [index],
                    "first_trade_id": pd.Series([pd.NA], dtype="Int64"),
                    "last_trade_id": pd.Series([pd.NA], dtype="Int64"),
                    "price": [100.0],
                    "quantity": [2.0],
                    "quote_quantity": [200.0],
                    "buyer_is_maker": [False],
                    "best_match": pd.Series([pd.NA], dtype="boolean"),
                    "signed_quantity": [2.0],
                }
            )
            pq.write_table(pa.Table.from_pandas(frame, schema=TRADE_SCHEMA), output)
            output_hash = hashlib.sha256(output.read_bytes()).hexdigest()
            _write_json(
                output.with_suffix(".manifest.json"),
                {
                    "exchange": "binance",
                    "market": market,
                    "dataset": "trades",
                    "symbol": symbol,
                    "period": period,
                    "source_path": str(source),
                    "source_sha256": source_hash,
                    "output_sha256": output_hash,
                    "row_count": 1,
                    "min_timestamp_utc": timestamp.isoformat(),
                    "max_timestamp_utc": timestamp.isoformat(),
                },
            )

    for symbol in ("BTCUSDT", "ETHUSDT", "SOLUSDT"):
        root = data_dir.joinpath(
            "gold",
            "binance-public-data",
            "v1",
            "frequency=1min",
            "dataset=trades",
            f"symbol={symbol}",
            f"period={period}",
        )
        lineage = {}
        for day in range(1, monthrange(2026, 7)[1] + 1):
            value = f"{period}-{day:02d}"
            daily = root / f"date={value}" / "manifest.json"
            _write_json(daily, {"day": value})
            lineage[value] = hashlib.sha256(daily.read_bytes()).hexdigest()
        continuous = root / "scope=continuous-period"
        output = continuous / "spot_perp_flow.parquet"
        output.parent.mkdir(parents=True, exist_ok=True)
        pd.DataFrame({"timestamp": [timestamp], "value": [1.0]}).to_parquet(output)
        output_hash = hashlib.sha256(output.read_bytes()).hexdigest()
        _write_json(
            continuous / "manifest.json",
            {
                "parameters": {
                    "symbol": symbol,
                    "period": period,
                    "dataset": "trades",
                    "frequency": "1min",
                    "day": None,
                    "cvd_scope": "continuous_period",
                    "clock_join": "exact_inner",
                },
                "source_manifest_sha256": lineage,
                "outputs": {
                    "spot_perp_flow": {
                        "path": str(output),
                        "sha256": output_hash,
                        "row_count": 1,
                    }
                },
            },
        )
    if corrupt_one_output:
        target = data_dir.joinpath(
            "silver/binance-public-data/v1/market=spot/dataset=trades/"
            "symbol=BTCUSDT/period=2026-07/part.parquet"
        )
        target.write_bytes(target.read_bytes() + b"corrupt")


def test_archive_month_quality_requires_complete_verified_lineage(tmp_path: Path) -> None:
    _seed_month(tmp_path)

    report = audit_binance_archive_month(tmp_path, period="2026-07")

    assert report["qualified"] is True
    assert report["oos_ready"] is True
    assert len(report["silver"]) == 6
    assert len(report["gold"]) == 3


def test_archive_month_quality_fails_closed_on_checksum_mismatch(tmp_path: Path) -> None:
    _seed_month(tmp_path, corrupt_one_output=True)

    report = audit_binance_archive_month(tmp_path, period="2026-07")

    assert report["qualified"] is False
    assert report["oos_ready"] is False
    failed = next(item for item in report["silver"] if not item["qualified"])
    assert failed["checks"]["silver_checksum"] is False
