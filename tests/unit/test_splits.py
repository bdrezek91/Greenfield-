"""time_series_split and purged_kfold_split must never leak future
information into a training set, and must stay strictly chronological.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from src.ml.splits import purged_kfold_split, time_series_split


def test_time_series_split_folds_are_contiguous_and_chronological() -> None:
    folds = time_series_split(100, 4)
    assert len(folds) == 4
    for train_idx, test_idx in folds:
        assert len(train_idx) > 0
        assert train_idx.max() < test_idx.min()  # train strictly before test


def test_time_series_split_test_folds_partition_the_series() -> None:
    folds = time_series_split(100, 4)
    all_test = np.concatenate([te for _, te in folds])
    assert sorted(all_test.tolist()) == list(range(20, 100))  # block 0 (0-19) never tested


def test_time_series_split_rejects_invalid_n_splits() -> None:
    with pytest.raises(ValueError):
        time_series_split(100, 0)


def test_time_series_split_rejects_too_few_rows() -> None:
    with pytest.raises(ValueError):
        time_series_split(3, 5)


def _label_end_times(ts: pd.Series, horizon: int) -> pd.Series:
    return ts.shift(-horizon).reset_index(drop=True)


def test_purged_kfold_no_training_row_overlaps_its_test_fold() -> None:
    n = 100
    ts = pd.Series(pd.date_range("2024-01-01", periods=n, freq="1h", tz="UTC"))
    label_end = _label_end_times(ts, horizon=5)

    folds = purged_kfold_split(ts, label_end, n_splits=5, embargo_fraction=0.02)
    assert len(folds) == 5

    for train_idx, test_idx in folds:
        test_start, test_end = ts.iloc[test_idx.min()], ts.iloc[test_idx.max()]
        for idx in train_idx:
            row_end = label_end.iloc[idx]
            if pd.isna(row_end):
                continue
            row_start = ts.iloc[idx]
            overlaps = row_start <= test_end and row_end >= test_start
            assert not overlaps, f"train idx {idx} leaks into test fold [{test_start}, {test_end}]"


def test_purged_kfold_excludes_rows_without_a_valid_label() -> None:
    n = 50
    ts = pd.Series(pd.date_range("2024-01-01", periods=n, freq="1h", tz="UTC"))
    label_end = _label_end_times(ts, horizon=5)  # last 5 rows have NaT label_end

    folds = purged_kfold_split(ts, label_end, n_splits=3, embargo_fraction=0.01)
    trailing_unlabeled = set(range(n - 5, n))
    for train_idx, _ in folds:
        assert not (set(train_idx.tolist()) & trailing_unlabeled)


def test_purged_kfold_test_folds_are_contiguous_and_cover_the_series() -> None:
    n = 60
    ts = pd.Series(pd.date_range("2024-01-01", periods=n, freq="1h", tz="UTC"))
    label_end = _label_end_times(ts, horizon=3)

    folds = purged_kfold_split(ts, label_end, n_splits=4, embargo_fraction=0.01)
    all_test = np.concatenate([te for _, te in folds])
    assert sorted(all_test.tolist()) == list(range(n))


def test_purged_kfold_rejects_mismatched_lengths() -> None:
    ts = pd.Series(pd.date_range("2024-01-01", periods=10, freq="1h", tz="UTC"))
    with pytest.raises(ValueError):
        purged_kfold_split(ts, ts.iloc[:5], n_splits=3)


def test_purged_kfold_rejects_too_few_splits() -> None:
    ts = pd.Series(pd.date_range("2024-01-01", periods=10, freq="1h", tz="UTC"))
    with pytest.raises(ValueError):
        purged_kfold_split(ts, ts, n_splits=1)


def test_larger_embargo_purges_more_training_rows() -> None:
    n = 100
    ts = pd.Series(pd.date_range("2024-01-01", periods=n, freq="1h", tz="UTC"))
    label_end = _label_end_times(ts, horizon=5)

    small_embargo = purged_kfold_split(ts, label_end, n_splits=5, embargo_fraction=0.01)
    large_embargo = purged_kfold_split(ts, label_end, n_splits=5, embargo_fraction=0.2)

    total_train_small = sum(len(tr) for tr, _ in small_embargo)
    total_train_large = sum(len(tr) for tr, _ in large_embargo)
    assert total_train_large < total_train_small
