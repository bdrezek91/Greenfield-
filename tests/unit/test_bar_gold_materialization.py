"""Historical candles materialize causal, immutable MC-like Gold."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from src.data.storage import write_klines
from src.features.bar_materialization import (
    BarGoldMaterializationError,
    materialize_daily_momentum_flow,
    write_bar_gold_report,
)
from src.features.store import FeaturePartManifest, verify_feature_part


def _history(root: Path) -> None:
    timestamps = pd.date_range("2024-01-01T18:00:00Z", periods=1_800, freq="1min")
    phase = np.arange(len(timestamps), dtype=float)
    close = 100 + phase * 0.01 + np.sin(phase / 8)
    frame = pd.DataFrame(
        {
            "timestamp": timestamps,
            "open": close - 0.05,
            "high": close + 0.20,
            "low": close - 0.20,
            "close": close,
            "volume": 10 + phase % 7,
            "turnover": (10 + phase % 7) * close,
            "symbol": "BTCUSDT",
            "timeframe": "1m",
        }
    )
    write_klines(frame, root)


def _build(root: Path):
    return materialize_daily_momentum_flow(
        root,
        venue="bybit",
        source_symbol="BTCUSDT",
        symbol="BTCUSDT",
        timeframe="1m",
        utc_date="2024-01-02",
        as_of=pd.Timestamp("2024-01-03T00:00:00Z"),
        code_version="commit-1",
        warmup_rows=128,
    )


def test_historical_day_materializes_verified_mc_like_gold(tmp_path: Path) -> None:
    _history(tmp_path)
    report = _build(tmp_path)
    report_path = write_bar_gold_report(tmp_path, report)

    assert report.qualified is True
    assert report.feature_set == "momentum-money-flow-bybit-1m-v1"
    assert report.gold_row_count > 0
    assert report.source_row_count == 1_568  # 128 warmup + 1,440 target bars
    assert report_path.is_file()
    assert write_bar_gold_report(tmp_path, report) == report_path
    for relative in report.gold_manifests:
        manifest = FeaturePartManifest.from_json(
            Path(tmp_path, relative).read_text(encoding="utf-8")
        )
        verify_feature_part(tmp_path, manifest)


def test_build_is_idempotent_when_future_rows_are_appended(tmp_path: Path) -> None:
    _history(tmp_path)
    first = _build(tmp_path)
    future = pd.DataFrame(
        {
            "timestamp": pd.to_datetime(["2024-01-03T00:00:00Z"]),
            "open": [110.0],
            "high": [111.0],
            "low": [109.0],
            "close": [110.5],
            "volume": [10.0],
            "turnover": [1105.0],
            "symbol": ["BTCUSDT"],
            "timeframe": ["1m"],
        }
    )
    write_klines(future, tmp_path)
    second = _build(tmp_path)

    assert second.dataset_version == first.dataset_version
    assert second.eligible_rows_sha256 == first.eligible_rows_sha256
    assert second.gold_manifests == first.gold_manifests
    assert second.source_parts_sha256 != first.source_parts_sha256


def test_open_day_and_corrupt_or_gapped_history_fail_closed(tmp_path: Path) -> None:
    _history(tmp_path)
    with pytest.raises(BarGoldMaterializationError, match="not closed"):
        materialize_daily_momentum_flow(
            tmp_path,
            venue="bybit",
            source_symbol="BTCUSDT",
            symbol="BTCUSDT",
            timeframe="1m",
            utc_date="2024-01-02",
            as_of=pd.Timestamp("2024-01-02T23:59:59Z"),
            code_version="commit-1",
        )

    part = next((tmp_path / "klines" / "BTCUSDT" / "1m").glob("*.parquet"))
    frame = pd.read_parquet(part).drop(index=400)
    frame.to_parquet(part, index=False)
    with pytest.raises(BarGoldMaterializationError, match="integrity"):
        _build(tmp_path)


def test_incomplete_closed_day_fails_closed(tmp_path: Path) -> None:
    _history(tmp_path)
    part = next((tmp_path / "klines" / "BTCUSDT" / "1m").glob("*.parquet"))
    frame = pd.read_parquet(part)
    frame = frame[frame["timestamp"] < pd.Timestamp("2024-01-02T23:59:00Z")]
    frame.to_parquet(part, index=False)

    with pytest.raises(BarGoldMaterializationError, match="complete build window"):
        _build(tmp_path)
