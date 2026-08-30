from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from src.data.binance_archive_rotation import rotate_binance_archive_month


def _json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value), encoding="utf-8")


def _seed(data_dir: Path, *, complete: bool = True) -> None:
    for market in ("spot", "futures-um"):
        for dataset in ("trades", "aggTrades"):
            for symbol in ("BTCUSDT", "ETHUSDT", "SOLUSDT"):
                if (
                    not complete
                    and market == "spot"
                    and dataset == "trades"
                    and symbol == "BTCUSDT"
                ):
                    continue
                source = data_dir.joinpath(
                    "external/binance-public-data",
                    market,
                    dataset,
                    symbol,
                    f"{symbol}-{dataset}-2026-07.zip",
                )
                source.parent.mkdir(parents=True, exist_ok=True)
                source.write_bytes(f"{market}:{dataset}:{symbol}".encode())
                _json(
                    source.with_suffix(".zip.manifest.json"),
                    {
                        "identity": (
                            f"{market.replace('-', '/')}:monthly:{dataset}:"
                            f"{symbol}:none:2026-07"
                        ),
                        "content_sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
                    },
                )
                silver = data_dir.joinpath(
                    "silver/binance-public-data/v1",
                    f"market={market}",
                    f"dataset={dataset}",
                    f"symbol={symbol}",
                    "period=2026-07",
                    "part.parquet",
                )
                silver.parent.mkdir(parents=True, exist_ok=True)
                silver.write_bytes(f"silver:{market}:{dataset}:{symbol}".encode())
                _json(
                    silver.with_suffix(".manifest.json"),
                    {
                        "market": market,
                        "dataset": dataset,
                        "symbol": symbol,
                        "period": "2026-07",
                    },
                )


def test_rotation_copies_verifies_then_prunes_exact_sources(tmp_path: Path) -> None:
    data = tmp_path / "data"
    backup = tmp_path / "backup"
    _seed(data)

    report = rotate_binance_archive_month(
        data,
        backup,
        period="2026-07",
        execute=True,
        prune_source=True,
    )

    assert report["qualified"] is True
    assert report["source_pruned"] is True
    assert report["file_count"] == 48
    assert not list(data.rglob("*.zip"))
    assert not list(data.rglob("part.parquet"))
    assert not list(data.rglob("*.manifest.json"))
    assert (backup / "2026-07/rotation-manifest.json").exists()
    assert (backup / "2026-07/prune-evidence.json").exists()


def test_rotation_refuses_incomplete_period_before_copy_or_prune(tmp_path: Path) -> None:
    data = tmp_path / "data"
    backup = tmp_path / "backup"
    _seed(data, complete=False)

    with pytest.raises(ValueError, match="requires complete"):
        rotate_binance_archive_month(
            data,
            backup,
            period="2026-07",
            execute=True,
            prune_source=True,
        )

    assert not backup.exists()
    assert list(data.rglob("*.zip"))
