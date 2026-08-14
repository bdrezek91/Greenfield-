"""Bootstrap and Deflated Sharpe Ratio must behave sanely on known inputs."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from src.analytics.robustness import (
    bootstrap_metric,
    confidence_interval,
    deflated_sharpe_ratio,
)


def test_bootstrap_metric_is_reproducible_with_seed() -> None:
    returns = pd.Series(np.random.default_rng(1).normal(0.001, 0.01, size=200))
    a = bootstrap_metric(returns, lambda s: s.mean(), n_iterations=500, seed=42)
    b = bootstrap_metric(returns, lambda s: s.mean(), n_iterations=500, seed=42)
    np.testing.assert_array_equal(a, b)


def test_bootstrap_metric_mean_converges_to_sample_mean() -> None:
    returns = pd.Series(np.random.default_rng(2).normal(0.002, 0.01, size=300))
    samples = bootstrap_metric(returns, lambda s: s.mean(), n_iterations=2000, seed=1)
    assert samples.mean() == pytest.approx(returns.mean(), abs=0.002)


def test_bootstrap_metric_empty_returns_empty_array() -> None:
    result = bootstrap_metric(pd.Series(dtype=float), lambda s: s.mean(), n_iterations=10)
    assert len(result) == 0


def test_confidence_interval_contains_median() -> None:
    samples = np.array([1.0, 2.0, 3.0, 4.0, 5.0])
    lo, hi = confidence_interval(samples, alpha=0.5)
    assert lo <= 3.0 <= hi


def test_confidence_interval_empty() -> None:
    lo, hi = confidence_interval(np.array([]))
    assert lo != lo  # nan
    assert hi != hi


def test_deflated_sharpe_decreases_with_more_trials() -> None:
    returns = pd.Series(np.random.default_rng(3).normal(0.001, 0.01, size=500))
    observed_sharpe = 0.1  # per-period Sharpe, matching this return series' scale

    result_few = deflated_sharpe_ratio(observed_sharpe, returns, n_trials=1)
    result_many = deflated_sharpe_ratio(observed_sharpe, returns, n_trials=1000)

    assert result_many.expected_max_sharpe_under_null > result_few.expected_max_sharpe_under_null
    assert result_many.deflated_sharpe_ratio < result_few.deflated_sharpe_ratio


def test_deflated_sharpe_increases_with_observed_sharpe() -> None:
    returns = pd.Series(np.random.default_rng(4).normal(0.001, 0.01, size=500))

    low = deflated_sharpe_ratio(0.2, returns, n_trials=50)
    high = deflated_sharpe_ratio(2.0, returns, n_trials=50)

    assert high.deflated_sharpe_ratio > low.deflated_sharpe_ratio


def test_deflated_sharpe_result_bounded_probability() -> None:
    returns = pd.Series(np.random.default_rng(5).normal(0.001, 0.01, size=500))
    result = deflated_sharpe_ratio(1.5, returns, n_trials=100)
    assert 0.0 <= result.deflated_sharpe_ratio <= 1.0


def test_deflated_sharpe_too_few_observations_is_nan() -> None:
    result = deflated_sharpe_ratio(1.0, pd.Series([0.01]), n_trials=10)
    assert result.expected_max_sharpe_under_null != result.expected_max_sharpe_under_null
