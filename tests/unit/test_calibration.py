"""Brier score and calibration curve must match known reference values."""

from __future__ import annotations

import numpy as np
import pytest

from src.ml.calibration import brier_score, calibration_curve


def test_brier_score_perfect_predictor_is_zero() -> None:
    y_true = np.array([1.0, 0.0, 1.0, 0.0])
    assert brier_score(y_true, y_true) == pytest.approx(0.0)


def test_brier_score_constant_half_on_50_50_outcomes() -> None:
    y_true = np.array([1.0, 0.0, 1.0, 0.0])
    y_prob = np.full(4, 0.5)
    assert brier_score(y_true, y_prob) == pytest.approx(0.25)


def test_brier_score_maximally_wrong_is_one() -> None:
    y_true = np.array([1.0, 0.0])
    y_prob = np.array([0.0, 1.0])
    assert brier_score(y_true, y_prob) == pytest.approx(1.0)


def test_brier_score_shape_mismatch_raises() -> None:
    with pytest.raises(ValueError):
        brier_score(np.array([1.0, 0.0]), np.array([0.5]))


def test_brier_score_empty_is_nan() -> None:
    result = brier_score(np.array([]), np.array([]))
    assert result != result  # nan


def test_calibration_curve_well_calibrated_bin() -> None:
    # 10 predictions all at 0.7, 7 positive outcomes -> observed freq 0.7.
    y_prob = np.full(10, 0.7)
    y_true = np.array([1] * 7 + [0] * 3, dtype=float)
    curve = calibration_curve(y_true, y_prob, n_bins=10)
    bin_idx = int(np.argmax(curve.bin_counts))  # the single bin all 10 predictions fall into
    assert curve.mean_predicted[bin_idx] == pytest.approx(0.7)
    assert curve.observed_frequency[bin_idx] == pytest.approx(0.7)
    assert curve.bin_counts[bin_idx] == 10


def test_calibration_curve_empty_bins_are_nan() -> None:
    y_prob = np.array([0.05, 0.05])
    y_true = np.array([0.0, 1.0])
    curve = calibration_curve(y_true, y_prob, n_bins=10)
    assert np.isnan(curve.mean_predicted[-1])
    assert curve.bin_counts[-1] == 0


def test_calibration_curve_shape_mismatch_raises() -> None:
    with pytest.raises(ValueError):
        calibration_curve(np.array([1.0]), np.array([0.5, 0.5]))


def test_calibration_curve_bin_counts_sum_to_n() -> None:
    rng = np.random.default_rng(0)
    y_prob = rng.uniform(0, 1, size=200)
    y_true = (rng.uniform(0, 1, size=200) < y_prob).astype(float)
    curve = calibration_curve(y_true, y_prob, n_bins=5)
    assert curve.bin_counts.sum() == 200
