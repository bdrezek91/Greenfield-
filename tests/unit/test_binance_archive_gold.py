from __future__ import annotations

import json
from datetime import date
from pathlib import Path
from types import SimpleNamespace

import pandas as pd
from typer.testing import CliRunner

from scripts.materialize_binance_archive_gold import PRICE_TICKS, app
from src.data.binance_archive_gold import materialize_binance_archive_gold


def _write_source(root: Path, market: str) -> None:
    path = root.joinpath(
        "silver",
        "binance-public-data",
        "v1",
        f"market={market}",
        "dataset=trades",
        "symbol=BTCUSDT",
        "period=2026-01",
        "part.parquet",
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    count = 100
    timestamps = pd.date_range("2026-01-01", periods=count, freq="1min", tz="UTC")
    frame = pd.DataFrame(
        {
            "timestamp": timestamps,
            "exchange": "binance",
            "market": market,
            "dataset": "trades",
            "symbol": "BTCUSDT",
            "trade_id": range(count),
            "price": [100.0 + (index % 10) * 0.1 for index in range(count)],
            "quantity": 1.0,
            "quote_quantity": [100.0 + (index % 10) * 0.1 for index in range(count)],
            "signed_quantity": [1.0 if index % 2 == 0 else -1.0 for index in range(count)],
        }
    )
    frame.to_parquet(path, index=False)
    path.with_suffix(".manifest.json").write_text(json.dumps({"ok": True}), encoding="utf-8")


def test_materialize_binance_archive_gold_builds_all_outputs_idempotently(
    tmp_path: Path,
) -> None:
    _write_source(tmp_path, "spot")
    _write_source(tmp_path, "futures-um")

    def usage(_: Path) -> SimpleNamespace:
        return SimpleNamespace(free=100_000_000)

    output, changed, manifest = materialize_binance_archive_gold(
        data_dir=tmp_path,
        symbol="BTCUSDT",
        period="2026-01",
        price_tick=0.1,
        minimum_free_bytes=1,
        disk_usage=usage,
    )
    _, changed_again, _ = materialize_binance_archive_gold(
        data_dir=tmp_path,
        symbol="BTCUSDT",
        period="2026-01",
        price_tick=0.1,
        minimum_free_bytes=1,
        disk_usage=usage,
    )

    assert changed
    assert not changed_again
    assert len(manifest["outputs"]) == 9
    assert manifest["parameters"]["clock_join"] == "exact_inner"
    assert (output / "spot_perp_flow.parquet").exists()
    synchronized = pd.read_parquet(output / "spot_perp_flow.parquet")
    assert len(synchronized) == 100


def test_daily_materialization_reads_only_requested_utc_day(tmp_path: Path) -> None:
    _write_source(tmp_path, "spot")
    _write_source(tmp_path, "futures-um")

    output, _, manifest = materialize_binance_archive_gold(
        data_dir=tmp_path,
        symbol="BTCUSDT",
        period="2026-01",
        day=date(2026, 1, 1),
        price_tick=0.1,
        minimum_free_bytes=1,
        disk_usage=lambda _: SimpleNamespace(free=100_000_000),
    )

    assert output.name == "date=2026-01-01"
    assert manifest["parameters"]["cvd_scope"] == "day"
    assert manifest["parameters"]["day"] == "2026-01-01"


def test_materialize_cli_accepts_string_day_option() -> None:
    result = CliRunner().invoke(app, ["--help"])

    assert result.exit_code == 0
    assert "--day" in result.stdout


def test_btc_footprint_uses_common_spot_perp_price_grid() -> None:
    assert PRICE_TICKS["BTCUSDT"] == 0.01
