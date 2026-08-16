"""MicrostructureBatchWriter: each flush is its own file, reads concatenate
in range, nothing is ever rewritten - see module docstring for why.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from src.data.microstructure_writer import read_range, write_batch


def _orderbook_rows(n: int, start: str = "2024-01-01") -> list[dict]:
    ts = pd.date_range(start, periods=n, freq="1s", tz="UTC")
    return [
        {
            "timestamp": t,
            "symbol": "BTCUSDT",
            "best_bid": 100.0,
            "best_ask": 100.1,
            "mid_price": 100.05,
            "spread": 0.1,
            "bid_qty_top": 1.0,
            "ask_qty_top": 1.0,
            "imbalance": 0.0,
        }
        for t in ts
    ]


def test_write_batch_then_read_range_round_trips(tmp_path: Path) -> None:
    rows = _orderbook_rows(5)
    write_batch(rows, tmp_path, "orderbook", "BTCUSDT")

    result = read_range(
        tmp_path,
        "orderbook",
        "BTCUSDT",
        start=pd.Timestamp("2024-01-01", tz="UTC"),
        end=pd.Timestamp("2024-01-02", tz="UTC"),
    )

    assert len(result) == 5
    assert result["timestamp"].is_monotonic_increasing


def test_multiple_flushes_do_not_overwrite_each_other(tmp_path: Path) -> None:
    write_batch(_orderbook_rows(3, start="2024-01-01T00:00:00"), tmp_path, "orderbook", "BTCUSDT")
    write_batch(_orderbook_rows(3, start="2024-01-01T01:00:00"), tmp_path, "orderbook", "BTCUSDT")

    result = read_range(
        tmp_path,
        "orderbook",
        "BTCUSDT",
        start=pd.Timestamp("2024-01-01", tz="UTC"),
        end=pd.Timestamp("2024-01-02", tz="UTC"),
    )
    assert len(result) == 6


def test_batch_spanning_midnight_splits_across_day_directories(tmp_path: Path) -> None:
    ts = [
        pd.Timestamp("2024-01-01T23:59:00", tz="UTC"),
        pd.Timestamp("2024-01-02T00:01:00", tz="UTC"),
    ]
    rows = [
        {
            "timestamp": t,
            "symbol": "BTCUSDT",
            "best_bid": 1.0,
            "best_ask": 1.0,
            "mid_price": 1.0,
            "spread": 0.0,
            "bid_qty_top": 1.0,
            "ask_qty_top": 1.0,
            "imbalance": 0.0,
        }
        for t in ts
    ]
    write_batch(rows, tmp_path, "orderbook", "BTCUSDT")

    day1 = tmp_path / "microstructure" / "orderbook" / "BTCUSDT" / "2024-01-01"
    day2 = tmp_path / "microstructure" / "orderbook" / "BTCUSDT" / "2024-01-02"
    assert list(day1.glob("*.parquet"))
    assert list(day2.glob("*.parquet"))


def test_read_range_respects_bounds(tmp_path: Path) -> None:
    write_batch(_orderbook_rows(10), tmp_path, "orderbook", "BTCUSDT")

    result = read_range(
        tmp_path,
        "orderbook",
        "BTCUSDT",
        start=pd.Timestamp("2024-01-01T00:00:03", tz="UTC"),
        end=pd.Timestamp("2024-01-01T00:00:05", tz="UTC"),
    )
    assert len(result) == 3


def test_read_missing_symbol_returns_empty_frame(tmp_path: Path) -> None:
    result = read_range(
        tmp_path,
        "orderbook",
        "NOPE",
        start=pd.Timestamp("2024-01-01", tz="UTC"),
        end=pd.Timestamp("2024-01-02", tz="UTC"),
    )
    assert result.empty


def test_write_batch_with_empty_rows_is_a_noop(tmp_path: Path) -> None:
    assert write_batch([], tmp_path, "orderbook", "BTCUSDT") is None


def test_unknown_stream_raises(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="unknown stream"):
        write_batch(_orderbook_rows(1), tmp_path, "bogus", "BTCUSDT")
