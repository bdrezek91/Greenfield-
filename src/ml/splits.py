"""Time-series and purged/embargoed splits.

Per docs/RESEARCH_METHODOLOGY.md section 25: never a random
`train_test_split`. Splits are chronological; `purged_kfold_split`
additionally removes training rows whose label window overlaps a test
fold's time range (purging) and adds a buffer after each test fold
(embargo) - the standard defense against label leakage when labels span
multiple bars forward (López de Prado's Purged K-Fold).
"""

from __future__ import annotations

import numpy as np
import pandas as pd


def time_series_split(n: int, n_splits: int) -> list[tuple[np.ndarray, np.ndarray]]:
    """Expanding-window chronological split: the series is cut into
    `n_splits + 1` contiguous blocks; fold i's (i=1..n_splits) test set is
    block i, and its train set is every block strictly before it (block 0
    through block i-1) - a plain chronological split, no purging. Block 0
    is never a test set (there's nothing before it to train on), so this
    always yields `n_splits` folds with a nonempty train set.
    """
    if n_splits < 1:
        raise ValueError("n_splits must be >= 1")
    if n < n_splits + 1:
        raise ValueError(f"need at least {n_splits + 1} rows for {n_splits} splits, got {n}")

    fold_bounds = np.linspace(0, n, n_splits + 2, dtype=int)
    folds = []
    for i in range(1, n_splits + 1):
        train_idx = np.arange(0, fold_bounds[i])
        test_idx = np.arange(fold_bounds[i], fold_bounds[i + 1])
        folds.append((train_idx, test_idx))
    return folds


def purged_kfold_split(
    timestamps: pd.Series,
    label_end_times: pd.Series,
    n_splits: int,
    embargo_fraction: float = 0.01,
) -> list[tuple[np.ndarray, np.ndarray]]:
    """K-Fold split where, for each fold, training rows are removed if
    their label window [timestamps[i], label_end_times[i]] overlaps the
    test fold's time range (purging), and an additional embargo period
    (a fraction of total series length) immediately after the test fold is
    also excluded from training, since labels starting there could still
    have been influenced by information leaking across the boundary.

    `timestamps` and `label_end_times` must be the same length, aligned by
    position (row i's label starts at timestamps[i] and ends at
    label_end_times[i]); rows with a NaT label_end_time (e.g. the last
    `horizon_bars` rows - see src.ml.labels) are excluded from training
    everywhere, since they have no valid label to train on regardless of
    fold, but may still appear in a test fold's index range positionally.
    """
    if len(timestamps) != len(label_end_times):
        raise ValueError("timestamps and label_end_times must be the same length")
    n = len(timestamps)
    if n_splits < 2:
        raise ValueError("n_splits must be >= 2")

    ts = timestamps.reset_index(drop=True)
    label_end = label_end_times.reset_index(drop=True)
    has_valid_label = label_end.notna()

    fold_bounds = np.linspace(0, n, n_splits + 1, dtype=int)
    total_span = ts.iloc[-1] - ts.iloc[0]
    embargo_delta = total_span * embargo_fraction

    folds = []
    for i in range(n_splits):
        test_start_idx, test_end_idx = fold_bounds[i], fold_bounds[i + 1]
        test_idx = np.arange(test_start_idx, test_end_idx)

        test_start_time = ts.iloc[test_start_idx]
        test_end_time = ts.iloc[test_end_idx - 1]
        embargo_end_time = test_end_time + embargo_delta

        overlaps_test_or_embargo = (ts <= embargo_end_time) & (label_end >= test_start_time)
        purge_mask = overlaps_test_or_embargo & has_valid_label

        train_mask = has_valid_label & ~purge_mask
        train_mask.iloc[test_start_idx:test_end_idx] = False
        train_idx = np.where(train_mask.to_numpy())[0]

        folds.append((train_idx, test_idx))
    return folds
