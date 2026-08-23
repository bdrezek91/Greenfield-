"""Binance klines Parquet storage must round-trip data, merge incremental
writes without duplicates, and never collide with Bybit's identically-
named symbols under the existing bare klines/ directory - the Binance
counterpart to test_storage.py's kline tests.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from src.data.binance_klines_storage import read_binance_klines, write_binance_klines
from src.data.schema import COLUMNS


def _frame(start: str, n: int, symbol: str = "BTCUSDT", timeframe: str = "1h") -> pd.DataFrame:
    ts = pd.date_range(start, periods=n, freq="1h", tz="UTC")
    return pd.DataFrame(
        {
            "timestamp": ts,
            "open": [100.0] * n,
            "high": [101.0] * n,
            "low": [99.0] * n,
            "close": [100.5] * n,
            "volume": [10.0] * n,
            "turnover": [1000.0] * n,
            "symbol": symbol,
            "timeframe": timeframe,
        }
    )[list(COLUMNS)]


def test_write_then_read_round_trip(tmp_path: Path) -> None:
    df = _frame("2024-01-01", 5)
    write_binance_klines(df, tmp_path)

    result = read_binance_klines(tmp_path, "BTCUSDT", "1h")

    assert len(result) == 5
    pd.testing.assert_series_equal(
        result["timestamp"].reset_index(drop=True), df["timestamp"].reset_index(drop=True)
    )


def test_incremental_write_merges_without_duplicates(tmp_path: Path) -> None:
    first = _frame("2024-01-01T00:00", 5)
    write_binance_klines(first, tmp_path)

    second = _frame("2024-01-01T03:00", 5)  # overlaps by 2 candles
    write_binance_klines(second, tmp_path)

    result = read_binance_klines(tmp_path, "BTCUSDT", "1h")
    assert len(result) == 8


def test_different_timeframes_are_separate_partitions(tmp_path: Path) -> None:
    write_binance_klines(_frame("2024-01-01", 5, timeframe="1h"), tmp_path)
    write_binance_klines(_frame("2024-01-01", 3, timeframe="4h"), tmp_path)

    assert len(read_binance_klines(tmp_path, "BTCUSDT", "1h")) == 5
    assert len(read_binance_klines(tmp_path, "BTCUSDT", "4h")) == 3


def test_read_missing_symbol_returns_empty_frame(tmp_path: Path) -> None:
    result = read_binance_klines(tmp_path, "BTCUSDT", "1h")
    assert result.empty


def test_does_not_collide_with_bybit_bare_klines_directory(tmp_path: Path) -> None:
    write_binance_klines(_frame("2024-01-01", 3), tmp_path)
    assert not (tmp_path / "klines").exists()
    assert (tmp_path / "binance_klines").exists()
