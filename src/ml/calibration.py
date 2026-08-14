"""Probability calibration diagnostics, per docs/PHASE_0_ARCHITECTURE_RESEARCH.md
section 26: any model that outputs P(win) must be checked for calibration.

Implemented from scratch (numpy/pandas) rather than via scikit-learn, since
no ML dependency is installed yet in Phase 11 (the framework phase - actual
models land in Phase 12, see src/ml/baseline.py's docstring).
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np


def brier_score(y_true: np.ndarray, y_prob: np.ndarray) -> float:
    """Mean squared error between predicted probabilities and binary
    outcomes. 0 = perfect, 0.25 = the score of a constant 0.5 predictor
    against a 50/50 outcome, 1 = maximally wrong.
    """
    y_true = np.asarray(y_true, dtype=float)
    y_prob = np.asarray(y_prob, dtype=float)
    if y_true.shape != y_prob.shape:
        raise ValueError("y_true and y_prob must be the same shape")
    if len(y_true) == 0:
        return float("nan")
    return float(np.mean((y_prob - y_true) ** 2))


@dataclass
class CalibrationCurve:
    bin_edges: np.ndarray
    mean_predicted: np.ndarray
    """Mean predicted probability within each bin. NaN for empty bins."""
    observed_frequency: np.ndarray
    """Observed fraction of positive outcomes within each bin. NaN for empty bins."""
    bin_counts: np.ndarray


def calibration_curve(y_true: np.ndarray, y_prob: np.ndarray, n_bins: int = 10) -> CalibrationCurve:
    """Reliability-diagram data: bin predictions into `n_bins` equal-width
    bins over [0, 1] and compare the mean predicted probability to the
    observed positive-outcome frequency in each bin. A well-calibrated
    model has mean_predicted ~= observed_frequency in every bin.
    """
    y_true = np.asarray(y_true, dtype=float)
    y_prob = np.asarray(y_prob, dtype=float)
    if y_true.shape != y_prob.shape:
        raise ValueError("y_true and y_prob must be the same shape")
    if n_bins < 1:
        raise ValueError("n_bins must be >= 1")

    bin_edges = np.linspace(0.0, 1.0, n_bins + 1)
    bin_idx = np.clip(np.digitize(y_prob, bin_edges[1:-1], right=True), 0, n_bins - 1)

    mean_predicted = np.full(n_bins, np.nan)
    observed_frequency = np.full(n_bins, np.nan)
    bin_counts = np.zeros(n_bins, dtype=int)

    for b in range(n_bins):
        mask = bin_idx == b
        count = int(mask.sum())
        bin_counts[b] = count
        if count > 0:
            mean_predicted[b] = float(y_prob[mask].mean())
            observed_frequency[b] = float(y_true[mask].mean())

    return CalibrationCurve(
        bin_edges=bin_edges,
        mean_predicted=mean_predicted,
        observed_frequency=observed_frequency,
        bin_counts=bin_counts,
    )
