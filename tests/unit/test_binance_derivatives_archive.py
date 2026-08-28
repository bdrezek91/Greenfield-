from __future__ import annotations

import json
import zipfile
from pathlib import Path
from types import SimpleNamespace

import pandas as pd
import pytest

from src.data.binance_derivatives_archive import normalize_binance_derivatives_archive


def _archive(tmp_path: Path, dataset: str, csv: str, *, period: str = "2026-07") -> Path:
    interval = "1m" if dataset != "metrics" else "none"
    cadence = "monthly" if dataset != "metrics" else "daily"
    source = tmp_path / f"BTCUSDT-{dataset}-{period}.zip"
    with zipfile.ZipFile(source, "w") as archive:
        archive.writestr(source.with_suffix(".csv").name, csv)
    source.with_suffix(".zip.manifest.json").write_text(
        json.dumps({"identity": f"futures/um:{cadence}:{dataset}:BTCUSDT:{interval}:{period}"}),
        encoding="utf-8",
    )
    return source


def _usage(_: Path) -> SimpleNamespace:
    return SimpleNamespace(free=100_000_000)


def test_normalize_reference_kline_is_typed_and_idempotent(tmp_path: Path) -> None:
    source = _archive(
        tmp_path,
        "markPriceKlines",
        "open_time,open,high,low,close,volume,close_time,quote_volume,count,taker_buy_volume,taker_buy_quote_volume,ignore\n"
        "1782864000000,100,102,99,101,0,1782864059999,0,60,0,0,0\n",
    )
    output, changed, metadata = normalize_binance_derivatives_archive(
        source, data_dir=tmp_path / "data", minimum_free_bytes=1, disk_usage=_usage
    )
    _, changed_again, _ = normalize_binance_derivatives_archive(
        source, data_dir=tmp_path / "data", minimum_free_bytes=1, disk_usage=_usage
    )
    frame = pd.read_parquet(output)
    assert changed and not changed_again
    assert metadata["row_count"] == 1
    assert frame.loc[0, "close"] == 101.0
    assert str(frame["timestamp"].dtype) == "datetime64[ns, UTC]"


def test_normalize_metrics_preserves_oi_and_positioning(tmp_path: Path) -> None:
    source = _archive(
        tmp_path,
        "metrics",
        "create_time,symbol,sum_open_interest,sum_open_interest_value,count_toptrader_long_short_ratio,sum_toptrader_long_short_ratio,count_long_short_ratio,sum_taker_long_short_vol_ratio\n"
        "2026-07-01 00:00:00,BTCUSDT,108532.354,6370849179.8,2.96,1.30,2.84,1.27\n",
        period="2026-07-01",
    )
    output, _, _ = normalize_binance_derivatives_archive(
        source, data_dir=tmp_path / "data", minimum_free_bytes=1, disk_usage=_usage
    )
    frame = pd.read_parquet(output)
    assert frame.loc[0, "sum_open_interest"] == pytest.approx(108532.354)
    assert frame.loc[0, "sum_taker_long_short_vol_ratio"] == pytest.approx(1.27)


def test_normalize_derivatives_rejects_duplicate_timestamp(tmp_path: Path) -> None:
    header = (
        "open_time,open,high,low,close,volume,close_time,quote_volume,count,"
        "taker_buy_volume,taker_buy_quote_volume,ignore\n"
    )
    row = "1782864000000,100,102,99,101,0,1782864059999,0,60,0,0,0\n"
    source = _archive(tmp_path, "premiumIndexKlines", header + row + row)
    with pytest.raises(ValueError, match="strictly increasing"):
        normalize_binance_derivatives_archive(
            source, data_dir=tmp_path / "data", minimum_free_bytes=1, disk_usage=_usage
        )
