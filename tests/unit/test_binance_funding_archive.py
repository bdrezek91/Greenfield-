from __future__ import annotations

import json
import zipfile
from pathlib import Path
from types import SimpleNamespace

import pandas as pd
import pytest

from src.data.binance_funding_archive import normalize_binance_funding_archive


def _archive(tmp_path: Path, *, csv: str) -> Path:
    source = tmp_path / "BTCUSDT-fundingRate-2020-01.zip"
    with zipfile.ZipFile(source, "w") as archive:
        archive.writestr("BTCUSDT-fundingRate-2020-01.csv", csv)
    source.with_suffix(".zip.manifest.json").write_text(
        json.dumps(
            {"identity": "futures/um:monthly:fundingRate:BTCUSDT:none:2020-01"}
        ),
        encoding="utf-8",
    )
    return source


def test_normalize_funding_archive_writes_typed_silver_and_is_idempotent(
    tmp_path: Path,
) -> None:
    source = _archive(
        tmp_path,
        csv=(
            "calc_time,funding_interval_hours,last_funding_rate\n"
            "1577836800000,8,-0.00012359\n"
            "1577865600000,8,0.00010000\n"
        ),
    )
    def usage(_: Path) -> SimpleNamespace:
        return SimpleNamespace(free=100_000_000)

    output, changed, metadata = normalize_binance_funding_archive(
        source, data_dir=tmp_path / "data", minimum_free_bytes=1, disk_usage=usage
    )
    _, changed_again, _ = normalize_binance_funding_archive(
        source, data_dir=tmp_path / "data", minimum_free_bytes=1, disk_usage=usage
    )

    frame = pd.read_parquet(output)
    assert changed
    assert not changed_again
    assert metadata["row_count"] == 2
    assert frame["funding_rate"].tolist() == [-0.00012359, 0.0001]
    assert str(frame["timestamp"].dtype) == "datetime64[ns, UTC]"


def test_normalize_funding_archive_rejects_duplicate_timestamp(tmp_path: Path) -> None:
    source = _archive(
        tmp_path,
        csv=(
            "calc_time,funding_interval_hours,last_funding_rate\n"
            "1577836800000,8,0.1\n"
            "1577836800000,8,0.2\n"
        ),
    )

    with pytest.raises(ValueError, match="strictly increasing"):
        normalize_binance_funding_archive(
            source,
            data_dir=tmp_path / "data",
            minimum_free_bytes=1,
            disk_usage=lambda _: SimpleNamespace(free=100_000_000),
        )
