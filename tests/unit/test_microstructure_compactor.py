"""Daily microstructure compaction: atomic merge, validate-before-swap,
never delete sources before the merged file is confirmed valid.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from src.data.microstructure_compactor import compact_all, compact_day
from src.data.microstructure_writer import read_range, write_batch


def _rows(symbol: str, n: int, start_hour: int) -> list[dict]:
    ts = pd.date_range(f"2024-01-01T{start_hour:02d}:00:00", periods=n, freq="1s", tz="UTC")
    return [{"timestamp": t, "symbol": symbol, "bid_price": 100.0, "ask_price": 100.1} for t in ts]


@pytest.fixture
def orderbook_dir(tmp_path: Path) -> Path:
    write_batch(_rows("BTCUSDT", 5, 0), tmp_path, "orderbook", "BTCUSDT")
    write_batch(_rows("BTCUSDT", 3, 1), tmp_path, "orderbook", "BTCUSDT")
    write_batch(_rows("BTCUSDT", 4, 2), tmp_path, "orderbook", "BTCUSDT")
    return tmp_path / "microstructure" / "orderbook" / "BTCUSDT" / "2024-01-01"


def test_compact_day_merges_files(orderbook_dir: Path) -> None:
    before = list(orderbook_dir.glob("*.parquet"))
    assert len(before) == 3

    result = compact_day(orderbook_dir)

    assert result.ok
    assert result.source_files == 3
    assert result.source_rows == 12
    assert result.merged_rows == 12
    after = list(orderbook_dir.glob("*.parquet"))
    assert len(after) == 1
    assert after[0].name.startswith("compacted-")


def test_compact_day_preserves_readable_data(orderbook_dir: Path) -> None:
    compact_day(orderbook_dir)
    data_dir = orderbook_dir.parents[3]
    df = read_range(
        data_dir,
        "orderbook",
        "BTCUSDT",
        pd.Timestamp("2024-01-01T00:00:00Z"),
        pd.Timestamp("2024-01-01T23:59:59Z"),
    )
    assert len(df) == 12


def test_compact_day_no_op_for_single_file(tmp_path: Path) -> None:
    write_batch(_rows("BTCUSDT", 2, 0), tmp_path, "orderbook", "BTCUSDT")
    directory = tmp_path / "microstructure" / "orderbook" / "BTCUSDT" / "2024-01-01"
    result = compact_day(directory)
    assert result.skipped_reason == "nothing to compact"
    assert len(list(directory.glob("*.parquet"))) == 1


def test_compact_day_missing_directory(tmp_path: Path) -> None:
    result = compact_day(tmp_path / "does-not-exist")
    assert not result.ok


def test_compact_day_is_idempotent(orderbook_dir: Path) -> None:
    first = compact_day(orderbook_dir)
    assert first.ok
    second = compact_day(orderbook_dir)
    assert second.skipped_reason == "nothing to compact"  # only the compacted file remains
    assert len(list(orderbook_dir.glob("*.parquet"))) == 1


def test_compact_all_skips_todays_directory(tmp_path: Path) -> None:
    today = pd.Timestamp.now(tz="UTC").strftime("%Y-%m-%d")
    write_batch(
        [
            {
                "timestamp": pd.Timestamp.now(tz="UTC"),
                "symbol": "BTCUSDT",
                "bid_price": 1,
                "ask_price": 1,
            }
        ],
        tmp_path,
        "orderbook",
        "BTCUSDT",
    )
    write_batch(
        [
            {
                "timestamp": pd.Timestamp.now(tz="UTC"),
                "symbol": "BTCUSDT",
                "bid_price": 1,
                "ask_price": 1,
            }
        ],
        tmp_path,
        "orderbook",
        "BTCUSDT",
    )
    today_dir = tmp_path / "microstructure" / "orderbook" / "BTCUSDT" / today
    assert len(list(today_dir.glob("*.parquet"))) == 2

    compact_all(tmp_path, streams=("orderbook",))
    assert len(list(today_dir.glob("*.parquet"))) == 2  # untouched


def test_compact_all_returns_empty_for_missing_data_dir(tmp_path: Path) -> None:
    assert compact_all(tmp_path) == []
