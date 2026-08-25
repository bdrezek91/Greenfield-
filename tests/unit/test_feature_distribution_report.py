"""Gold distributions are exact, verified, and immutable evidence."""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from src.features.distribution_report import (
    FeatureDistributionError,
    audit_feature_distribution,
    write_feature_distribution_report,
)
from src.features.store import FeatureStore, FeatureStoreError

_DATASET = "a" * 64


def _gold(root: Path) -> None:
    frame = pd.DataFrame(
        {
            "timestamp": pd.to_datetime(["2024-01-01T23:59:00Z", "2024-01-02T00:00:00Z"]),
            "max_source_timestamp": pd.to_datetime(
                ["2024-01-01T23:58:59Z", "2024-01-01T23:59:59Z"]
            ),
            "delta": [-2.0, 4.0],
            "constant_flag": [0, 0],
        }
    )
    FeatureStore(root).write(
        frame,
        feature_set="test-flow-v1",
        symbol="BTCUSDT",
        dataset_version=_DATASET,
        code_version="commit-1",
    )


def test_exact_gold_tuple_has_reproducible_distribution_report(tmp_path: Path) -> None:
    _gold(tmp_path)
    report = audit_feature_distribution(
        tmp_path,
        feature_set="test-flow-v1",
        symbol="BTCUSDT",
        dataset_version=_DATASET,
        code_version="commit-1",
    )
    path = write_feature_distribution_report(tmp_path, report)

    assert report.qualified is True
    assert report.manifest_count == 2
    assert report.row_count == 2
    assert [item.name for item in report.metrics] == ["constant_flag", "delta"]
    assert report.metrics[1].minimum == -2.0
    assert report.metrics[1].maximum == 4.0
    assert report.warnings == ("CONSTANT_FEATURE:constant_flag",)
    assert write_feature_distribution_report(tmp_path, report) == path


def test_wrong_version_and_corrupt_gold_fail_closed(tmp_path: Path) -> None:
    _gold(tmp_path)
    with pytest.raises(FeatureDistributionError, match="no Gold"):
        audit_feature_distribution(
            tmp_path,
            feature_set="test-flow-v1",
            symbol="BTCUSDT",
            dataset_version="b" * 64,
            code_version="commit-1",
        )

    part = next(tmp_path.rglob("*.parquet"))
    part.write_bytes(b"corrupt")
    with pytest.raises(FeatureStoreError, match="checksum"):
        audit_feature_distribution(
            tmp_path,
            feature_set="test-flow-v1",
            symbol="BTCUSDT",
            dataset_version=_DATASET,
            code_version="commit-1",
        )
