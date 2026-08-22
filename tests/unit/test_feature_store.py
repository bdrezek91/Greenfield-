"""Gold feature storage is causal, immutable, and reproducible."""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from src.features.store import FeatureStore, FeatureStoreError, verify_feature_part


def _frame() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "timestamp": pd.to_datetime(["2026-08-22T10:00:00Z", "2026-08-22T10:01:00Z"]),
            "max_source_timestamp": pd.to_datetime(
                ["2026-08-22T09:59:59Z", "2026-08-22T10:00:59Z"]
            ),
            "cvd_1m": [1.0, 2.5],
            "book_imbalance": [0.1, -0.2],
        }
    )


def test_feature_part_round_trip_and_idempotence(tmp_path: Path) -> None:
    store = FeatureStore(tmp_path)
    kwargs = {
        "feature_set": "microstructure-v1",
        "symbol": "BTCUSDT",
        "dataset_version": "a" * 64,
        "code_version": "commit-123",
    }
    first = store.write(_frame(), **kwargs)
    second = store.write(_frame().iloc[::-1], **kwargs)

    assert first == second
    assert len(first) == 1
    assert first[0].feature_columns == ("book_imbalance", "cvd_1m")
    assert first[0].row_count == 2
    verify_feature_part(tmp_path, first[0])
    assert Path(tmp_path, first[0].manifest_path).is_file()


def test_future_source_is_rejected(tmp_path: Path) -> None:
    frame = _frame()
    frame.loc[1, "max_source_timestamp"] = pd.Timestamp("2026-08-22T10:02:00Z")
    with pytest.raises(FeatureStoreError, match="future source"):
        FeatureStore(tmp_path).write(
            frame,
            feature_set="microstructure-v1",
            symbol="BTCUSDT",
            dataset_version="a" * 64,
            code_version="commit",
        )


@pytest.mark.parametrize("bad", [float("nan"), float("inf"), float("-inf")])
def test_null_or_non_finite_feature_is_rejected(tmp_path: Path, bad: float) -> None:
    frame = _frame()
    frame.loc[0, "cvd_1m"] = bad
    with pytest.raises(FeatureStoreError, match="null or non-finite"):
        FeatureStore(tmp_path).write(
            frame,
            feature_set="microstructure-v1",
            symbol="BTCUSDT",
            dataset_version="a" * 64,
            code_version="commit",
        )


def test_tampering_is_detected(tmp_path: Path) -> None:
    manifest = FeatureStore(tmp_path).write(
        _frame(),
        feature_set="microstructure-v1",
        symbol="BTCUSDT",
        dataset_version="a" * 64,
        code_version="commit",
    )[0]
    Path(tmp_path, manifest.part_path).write_bytes(b"tampered")
    with pytest.raises(FeatureStoreError, match="content checksum"):
        verify_feature_part(tmp_path, manifest)
