"""OKX derivatives-statistics Parquet storage must round-trip data and
merge incremental writes without duplicates - the OKX counterpart to
test_binance_derivatives_storage.py, and must never collide with Bybit's
or Binance's data under their own directories.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from src.data.okx_derivatives_storage import (
    read_okx_long_short_ratio,
    read_okx_open_interest,
    write_okx_long_short_ratio,
    write_okx_open_interest,
)


def _oi_frame(start: str, n: int, inst_id: str = "BTC-USDT-SWAP") -> pd.DataFrame:
    ts = pd.date_range(start, periods=n, freq="1min", tz="UTC")
    return pd.DataFrame(
        {
            "timestamp": ts,
            "inst_id": inst_id,
            "open_interest": [3_000_000.0] * n,
            "open_interest_ccy": [30_000.0] * n,
            "open_interest_usd": [2_500_000_000.0] * n,
        }
    )


def _ratio_frame(start: str, n: int, inst_id: str = "BTC-USDT-SWAP") -> pd.DataFrame:
    ts = pd.date_range(start, periods=n, freq="5min", tz="UTC")
    return pd.DataFrame(
        {"timestamp": ts, "inst_id": inst_id, "long_short_ratio": [1.05] * n}
    )


def test_open_interest_write_then_read_round_trip(tmp_path: Path) -> None:
    df = _oi_frame("2024-01-01", 5)
    write_okx_open_interest(df, tmp_path)

    result = read_okx_open_interest(tmp_path, "BTC-USDT-SWAP")

    assert len(result) == 5
    pd.testing.assert_series_equal(
        result["timestamp"].reset_index(drop=True), df["timestamp"].reset_index(drop=True)
    )


def test_open_interest_incremental_write_merges_without_duplicates(tmp_path: Path) -> None:
    first = _oi_frame("2024-01-01T00:00", 5)
    write_okx_open_interest(first, tmp_path)

    second = _oi_frame("2024-01-01T00:03", 5)  # overlaps by 2 readings
    write_okx_open_interest(second, tmp_path)

    result = read_okx_open_interest(tmp_path, "BTC-USDT-SWAP")
    assert len(result) == 8


def test_open_interest_read_missing_inst_id_returns_empty_frame(tmp_path: Path) -> None:
    result = read_okx_open_interest(tmp_path, "BTC-USDT-SWAP")
    assert result.empty


def test_open_interest_does_not_collide_with_other_exchanges(tmp_path: Path) -> None:
    write_okx_open_interest(_oi_frame("2024-01-01", 3), tmp_path)
    assert not (tmp_path / "open_interest").exists()
    assert not (tmp_path / "binance_open_interest").exists()
    assert (tmp_path / "okx_open_interest").exists()


def test_long_short_ratio_write_then_read_round_trip(tmp_path: Path) -> None:
    df = _ratio_frame("2024-01-01", 5)
    write_okx_long_short_ratio(df, tmp_path, "5m")

    result = read_okx_long_short_ratio(tmp_path, "BTC-USDT-SWAP", "5m")

    assert len(result) == 5
    pd.testing.assert_series_equal(
        result["timestamp"].reset_index(drop=True), df["timestamp"].reset_index(drop=True)
    )


def test_long_short_ratio_incremental_write_merges_without_duplicates(tmp_path: Path) -> None:
    first = _ratio_frame("2024-01-01T00:00", 5)
    write_okx_long_short_ratio(first, tmp_path, "5m")

    second = _ratio_frame("2024-01-01T00:15", 5)  # overlaps by 2 readings
    write_okx_long_short_ratio(second, tmp_path, "5m")

    result = read_okx_long_short_ratio(tmp_path, "BTC-USDT-SWAP", "5m")
    assert len(result) == 8


def test_long_short_ratio_different_periods_are_separate_partitions(tmp_path: Path) -> None:
    write_okx_long_short_ratio(_ratio_frame("2024-01-01", 5), tmp_path, "5m")
    write_okx_long_short_ratio(_ratio_frame("2024-01-01", 3), tmp_path, "1H")

    assert len(read_okx_long_short_ratio(tmp_path, "BTC-USDT-SWAP", "5m")) == 5
    assert len(read_okx_long_short_ratio(tmp_path, "BTC-USDT-SWAP", "1H")) == 3


def test_long_short_ratio_read_missing_inst_id_returns_empty_frame(tmp_path: Path) -> None:
    result = read_okx_long_short_ratio(tmp_path, "BTC-USDT-SWAP", "5m")
    assert result.empty
