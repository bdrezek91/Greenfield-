"""Funding-rate/open-interest Parquet storage must round-trip data and merge
incremental writes without duplicates - the funding/OI counterpart to
test_storage.py.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from src.data.storage import (
    read_funding,
    read_open_interest,
    write_funding,
    write_open_interest,
)


def _funding_frame(start: str, n: int, symbol: str = "BTCUSDT") -> pd.DataFrame:
    ts = pd.date_range(start, periods=n, freq="8h", tz="UTC")
    return pd.DataFrame({"timestamp": ts, "symbol": symbol, "funding_rate": [0.0001] * n})


def _oi_frame(start: str, n: int, symbol: str = "BTCUSDT") -> pd.DataFrame:
    ts = pd.date_range(start, periods=n, freq="1h", tz="UTC")
    return pd.DataFrame({"timestamp": ts, "symbol": symbol, "open_interest": [1000.0] * n})


class TestFundingStorage:
    def test_write_then_read_round_trip(self, tmp_path: Path) -> None:
        df = _funding_frame("2024-01-01", 5)
        write_funding(df, tmp_path)

        result = read_funding(tmp_path, "BTCUSDT")

        assert len(result) == 5
        pd.testing.assert_series_equal(
            result["timestamp"].reset_index(drop=True), df["timestamp"].reset_index(drop=True)
        )

    def test_incremental_write_merges_without_duplicates(self, tmp_path: Path) -> None:
        first = _funding_frame("2024-01-01", 5)
        write_funding(first, tmp_path)

        second = _funding_frame("2024-01-01T16:00:00", 5)  # overlaps by 3
        write_funding(second, tmp_path)

        result = read_funding(tmp_path, "BTCUSDT")
        assert len(result) == 7
        assert result["timestamp"].duplicated().sum() == 0
        assert result["timestamp"].is_monotonic_increasing

    def test_read_missing_symbol_returns_empty_frame(self, tmp_path: Path) -> None:
        assert read_funding(tmp_path, "NOPE").empty


class TestOpenInterestStorage:
    def test_write_then_read_round_trip(self, tmp_path: Path) -> None:
        df = _oi_frame("2024-01-01", 5)
        write_open_interest(df, tmp_path, interval_time="1h")

        result = read_open_interest(tmp_path, "BTCUSDT", interval_time="1h")

        assert len(result) == 5
        pd.testing.assert_series_equal(
            result["timestamp"].reset_index(drop=True), df["timestamp"].reset_index(drop=True)
        )

    def test_different_intervals_are_stored_separately(self, tmp_path: Path) -> None:
        df = _oi_frame("2024-01-01", 5)
        write_open_interest(df, tmp_path, interval_time="1h")
        write_open_interest(df, tmp_path, interval_time="5min")

        assert len(read_open_interest(tmp_path, "BTCUSDT", interval_time="1h")) == 5
        assert len(read_open_interest(tmp_path, "BTCUSDT", interval_time="5min")) == 5
        assert read_open_interest(tmp_path, "BTCUSDT", interval_time="4h").empty

    def test_incremental_write_merges_without_duplicates(self, tmp_path: Path) -> None:
        first = _oi_frame("2024-01-01", 5)
        write_open_interest(first, tmp_path, interval_time="1h")

        second = _oi_frame("2024-01-01T03:00:00", 5)  # overlaps by 2
        write_open_interest(second, tmp_path, interval_time="1h")

        result = read_open_interest(tmp_path, "BTCUSDT", interval_time="1h")
        assert len(result) == 8
        assert result["timestamp"].duplicated().sum() == 0

    def test_read_missing_symbol_returns_empty_frame(self, tmp_path: Path) -> None:
        assert read_open_interest(tmp_path, "NOPE", interval_time="1h").empty
