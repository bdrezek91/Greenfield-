"""Long/short-ratio Parquet storage must round-trip data and merge
incremental writes without duplicates - the long/short-ratio counterpart
to test_storage_funding.py.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from src.data.storage import read_long_short_ratio, write_long_short_ratio


def _ratio_frame(start: str, n: int, symbol: str = "BTCUSDT") -> pd.DataFrame:
    ts = pd.date_range(start, periods=n, freq="5min", tz="UTC")
    return pd.DataFrame(
        {"timestamp": ts, "symbol": symbol, "buy_ratio": [0.55] * n, "sell_ratio": [0.45] * n}
    )


def test_write_then_read_round_trip(tmp_path: Path) -> None:
    df = _ratio_frame("2024-01-01", 5)
    write_long_short_ratio(df, tmp_path, "5min")

    result = read_long_short_ratio(tmp_path, "BTCUSDT", "5min")

    assert len(result) == 5
    pd.testing.assert_series_equal(
        result["timestamp"].reset_index(drop=True), df["timestamp"].reset_index(drop=True)
    )


def test_incremental_write_merges_without_duplicates(tmp_path: Path) -> None:
    first = _ratio_frame("2024-01-01T00:00", 5)
    write_long_short_ratio(first, tmp_path, "5min")

    second = _ratio_frame("2024-01-01T00:15", 5)  # overlaps by 2 readings
    write_long_short_ratio(second, tmp_path, "5min")

    result = read_long_short_ratio(tmp_path, "BTCUSDT", "5min")
    assert len(result) == 8


def test_different_periods_are_separate_partitions(tmp_path: Path) -> None:
    write_long_short_ratio(_ratio_frame("2024-01-01", 5), tmp_path, "5min")
    write_long_short_ratio(_ratio_frame("2024-01-01", 3), tmp_path, "1h")

    assert len(read_long_short_ratio(tmp_path, "BTCUSDT", "5min")) == 5
    assert len(read_long_short_ratio(tmp_path, "BTCUSDT", "1h")) == 3


def test_read_missing_symbol_returns_empty_frame(tmp_path: Path) -> None:
    result = read_long_short_ratio(tmp_path, "BTCUSDT", "5min")
    assert result.empty
