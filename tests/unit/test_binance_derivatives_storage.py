"""Binance derivatives-statistics Parquet storage must round-trip data and
merge incremental writes without duplicates - the Binance counterpart to
test_storage_long_short_ratio.py / test_storage_funding.py, and must never
collide with Bybit's identically-symbol-named data under the existing
bare open_interest/long_short_ratio directories.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from src.data.binance_derivatives_storage import (
    read_binance_long_short_ratio,
    read_binance_open_interest,
    write_binance_long_short_ratio,
    write_binance_open_interest,
)


def _oi_frame(start: str, n: int, symbol: str = "BTCUSDT") -> pd.DataFrame:
    ts = pd.date_range(start, periods=n, freq="5min", tz="UTC")
    return pd.DataFrame(
        {
            "timestamp": ts,
            "symbol": symbol,
            "open_interest": [100000.0] * n,
            "open_interest_value": [8_000_000_000.0] * n,
        }
    )


def _ratio_frame(start: str, n: int, symbol: str = "BTCUSDT") -> pd.DataFrame:
    ts = pd.date_range(start, periods=n, freq="5min", tz="UTC")
    return pd.DataFrame(
        {
            "timestamp": ts,
            "symbol": symbol,
            "long_account": [0.51] * n,
            "short_account": [0.49] * n,
            "long_short_ratio": [1.04] * n,
        }
    )


def test_open_interest_write_then_read_round_trip(tmp_path: Path) -> None:
    df = _oi_frame("2024-01-01", 5)
    write_binance_open_interest(df, tmp_path, "5m")

    result = read_binance_open_interest(tmp_path, "BTCUSDT", "5m")

    assert len(result) == 5
    pd.testing.assert_series_equal(
        result["timestamp"].reset_index(drop=True), df["timestamp"].reset_index(drop=True)
    )


def test_open_interest_incremental_write_merges_without_duplicates(tmp_path: Path) -> None:
    first = _oi_frame("2024-01-01T00:00", 5)
    write_binance_open_interest(first, tmp_path, "5m")

    second = _oi_frame("2024-01-01T00:15", 5)  # overlaps by 2 readings
    write_binance_open_interest(second, tmp_path, "5m")

    result = read_binance_open_interest(tmp_path, "BTCUSDT", "5m")
    assert len(result) == 8


def test_open_interest_different_periods_are_separate_partitions(tmp_path: Path) -> None:
    write_binance_open_interest(_oi_frame("2024-01-01", 5), tmp_path, "5m")
    write_binance_open_interest(_oi_frame("2024-01-01", 3), tmp_path, "1h")

    assert len(read_binance_open_interest(tmp_path, "BTCUSDT", "5m")) == 5
    assert len(read_binance_open_interest(tmp_path, "BTCUSDT", "1h")) == 3


def test_open_interest_read_missing_symbol_returns_empty_frame(tmp_path: Path) -> None:
    result = read_binance_open_interest(tmp_path, "BTCUSDT", "5m")
    assert result.empty


def test_open_interest_does_not_collide_with_bybit_bare_directory(tmp_path: Path) -> None:
    write_binance_open_interest(_oi_frame("2024-01-01", 3), tmp_path, "5m")
    assert not (tmp_path / "open_interest").exists()
    assert (tmp_path / "binance_open_interest").exists()


def test_long_short_ratio_write_then_read_round_trip(tmp_path: Path) -> None:
    df = _ratio_frame("2024-01-01", 5)
    write_binance_long_short_ratio(df, tmp_path, "5m")

    result = read_binance_long_short_ratio(tmp_path, "BTCUSDT", "5m")

    assert len(result) == 5
    pd.testing.assert_series_equal(
        result["timestamp"].reset_index(drop=True), df["timestamp"].reset_index(drop=True)
    )


def test_long_short_ratio_incremental_write_merges_without_duplicates(tmp_path: Path) -> None:
    first = _ratio_frame("2024-01-01T00:00", 5)
    write_binance_long_short_ratio(first, tmp_path, "5m")

    second = _ratio_frame("2024-01-01T00:15", 5)  # overlaps by 2 readings
    write_binance_long_short_ratio(second, tmp_path, "5m")

    result = read_binance_long_short_ratio(tmp_path, "BTCUSDT", "5m")
    assert len(result) == 8


def test_long_short_ratio_read_missing_symbol_returns_empty_frame(tmp_path: Path) -> None:
    result = read_binance_long_short_ratio(tmp_path, "BTCUSDT", "5m")
    assert result.empty
