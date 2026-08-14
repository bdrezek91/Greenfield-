"""Parquet storage must round-trip data and merge incremental writes without duplicates."""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from src.data.storage import read_klines, write_klines


def _frame(start: str, n: int, symbol: str = "BTCUSD", timeframe: str = "1h") -> pd.DataFrame:
    ts = pd.date_range(start, periods=n, freq="1h", tz="UTC")
    return pd.DataFrame(
        {
            "timestamp": ts,
            "open": [1.0] * n,
            "high": [1.0] * n,
            "low": [1.0] * n,
            "close": [1.0] * n,
            "volume": [1.0] * n,
            "turnover": [1.0] * n,
            "symbol": symbol,
            "timeframe": timeframe,
        }
    )


def test_write_then_read_round_trip(tmp_path: Path) -> None:
    df = _frame("2024-01-01", 5)
    write_klines(df, tmp_path)

    result = read_klines(tmp_path, "BTCUSD", "1h")

    assert len(result) == 5
    pd.testing.assert_series_equal(
        result["timestamp"].reset_index(drop=True), df["timestamp"].reset_index(drop=True)
    )


def test_write_splits_across_month_boundary(tmp_path: Path) -> None:
    df = _frame("2024-01-30", 72)  # 3 days -> crosses into February
    written = write_klines(df, tmp_path)

    assert len(written) == 2
    assert {p.stem for p in written} == {"2024-01", "2024-02"}


def test_incremental_write_merges_without_duplicates(tmp_path: Path) -> None:
    first = _frame("2024-01-01", 5)
    write_klines(first, tmp_path)

    # Overlaps by 2 candles and adds 3 new ones.
    second = _frame("2024-01-01T03:00:00", 5)
    write_klines(second, tmp_path)

    result = read_klines(tmp_path, "BTCUSD", "1h")
    assert len(result) == 8
    assert result["timestamp"].duplicated().sum() == 0
    assert result["timestamp"].is_monotonic_increasing


def test_read_missing_symbol_returns_empty_frame(tmp_path: Path) -> None:
    result = read_klines(tmp_path, "NOPE", "1h")
    assert result.empty


def test_read_with_date_slicing(tmp_path: Path) -> None:
    df = _frame("2024-01-01", 10)
    write_klines(df, tmp_path)

    result = read_klines(
        tmp_path,
        "BTCUSD",
        "1h",
        start=pd.Timestamp("2024-01-01T03:00:00", tz="UTC"),
        end=pd.Timestamp("2024-01-01T05:00:00", tz="UTC"),
    )
    assert len(result) == 3
