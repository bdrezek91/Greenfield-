"""Dataset snapshots are reproducible and enforce receive-time cutoffs."""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import pytest

from src.data.dataset_catalog import (
    DatasetCatalogError,
    build_dataset_snapshot,
    write_dataset_snapshot,
)
from src.data.normalized_event import normalize_bybit_event
from src.data.normalized_store import AtomicNormalizedWriter
from src.data.raw_event import parse_bybit_message


def _write_two_trades(root: Path) -> None:
    raw = parse_bybit_message(
        json.dumps(
            {
                "topic": "publicTrade.BTCUSDT",
                "type": "snapshot",
                "ts": 1_700_000_000_020,
                "data": [
                    {
                        "T": 1_700_000_000_001,
                        "s": "BTCUSDT",
                        "S": "Buy",
                        "v": "1",
                        "p": "2",
                        "i": "a",
                    },
                    {
                        "T": 1_700_000_000_019,
                        "s": "BTCUSDT",
                        "S": "Sell",
                        "v": "1",
                        "p": "3",
                        "i": "b",
                    },
                ],
            },
            separators=(",", ":"),
        ),
        receive_ts_ns=1_700_000_000_021_000_000,
        receive_sequence=1,
        connection_id="c",
    )
    manifest = AtomicNormalizedWriter(root).write_source_part(
        list(normalize_bybit_event(raw)),
        source_events_sha256="a" * 64,
        source_part_path="raw/source.parquet",
        utc_date="2023-11-14",
    )
    assert manifest is not None


def test_snapshot_is_reproducible_and_written_immutably(tmp_path: Path) -> None:
    _write_two_trades(tmp_path)
    cutoff = pd.Timestamp(1_700_000_000_022, unit="ms", tz="UTC")

    first = build_dataset_snapshot(
        tmp_path, as_of=cutoff, code_version="commit-123", symbol="BTCUSDT"
    )
    second = build_dataset_snapshot(
        tmp_path, as_of=cutoff, code_version="commit-123", symbol="BTCUSDT"
    )
    path = write_dataset_snapshot(tmp_path, first)

    assert first == second
    assert first.dataset_version == second.dataset_version
    assert first.eligible_row_count == 2
    assert first.part_count == 1
    assert path.is_file()
    assert write_dataset_snapshot(tmp_path, second) == path


def test_receive_time_prevents_late_data_from_entering_snapshot(tmp_path: Path) -> None:
    _write_two_trades(tmp_path)
    with pytest.raises(DatasetCatalogError, match="no Silver rows"):
        build_dataset_snapshot(
            tmp_path,
            as_of=pd.Timestamp(1_700_000_000_020, unit="ms", tz="UTC"),
            code_version="commit-123",
        )


def test_code_and_cutoff_change_dataset_version(tmp_path: Path) -> None:
    _write_two_trades(tmp_path)
    cutoff = pd.Timestamp(1_700_000_000_022, unit="ms", tz="UTC")
    a = build_dataset_snapshot(tmp_path, as_of=cutoff, code_version="a")
    b = build_dataset_snapshot(tmp_path, as_of=cutoff, code_version="b")
    c = build_dataset_snapshot(
        tmp_path, as_of=cutoff + pd.Timedelta(seconds=1), code_version="a"
    )
    assert len({a.dataset_version, b.dataset_version, c.dataset_version}) == 3


def test_naive_cutoff_is_rejected(tmp_path: Path) -> None:
    with pytest.raises(DatasetCatalogError, match="timezone-aware"):
        build_dataset_snapshot(
            tmp_path, as_of=pd.Timestamp("2026-01-01"), code_version="commit"
        )
