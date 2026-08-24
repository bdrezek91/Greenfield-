from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pandas as pd
import pytest

from src.data.atomic_parquet import merge_atomic_parquet


def _write(path: Path, frame: pd.DataFrame) -> None:
    merge_atomic_parquet(path, frame, deduplicate_on=("id",), sort_by=("id",))


def test_failed_write_preserves_previous_partition_and_removes_temp(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "partition.parquet"
    _write(path, pd.DataFrame({"id": [1], "value": ["old"]}))
    original = path.read_bytes()

    def fail_write(*args: object, **kwargs: object) -> None:
        raise OSError("simulated write failure")

    monkeypatch.setattr(pd.DataFrame, "to_parquet", fail_write)
    with pytest.raises(OSError, match="simulated"):
        _write(path, pd.DataFrame({"id": [2], "value": ["new"]}))

    assert path.read_bytes() == original
    assert list(tmp_path.glob(".partition.parquet.*.tmp")) == []


def test_concurrent_writers_do_not_lose_rows(tmp_path: Path) -> None:
    path = tmp_path / "partition.parquet"

    def write_row(value: int) -> None:
        _write(path, pd.DataFrame({"id": [value], "value": [f"v{value}"]}))

    with ThreadPoolExecutor(max_workers=4) as pool:
        list(pool.map(write_row, range(20)))

    result = pd.read_parquet(path)
    assert result["id"].tolist() == list(range(20))
    assert path.with_suffix(".parquet.lock").exists()


def test_replay_is_deduplicated_deterministically(tmp_path: Path) -> None:
    path = tmp_path / "partition.parquet"
    frame = pd.DataFrame({"id": [2, 1, 1], "value": ["two", "one", "ignored"]})
    _write(path, frame)
    _write(path, frame)
    result = pd.read_parquet(path)
    assert result["id"].tolist() == [1, 2]
