"""Bootstrap and Deflated Sharpe Ratio must behave sanely on known inputs."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from src.analytics.robustness import (
    bootstrap_metric,
    confidence_interval,
    deflated_sharpe_ratio,
    probability_of_backtest_overfitting,
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


class TestProbabilityOfBacktestOverfitting:
    def test_rejects_odd_n_partitions(self) -> None:
        matrix = pd.DataFrame(np.random.default_rng(0).normal(size=(60, 5)))
        with pytest.raises(ValueError, match="even"):
            probability_of_backtest_overfitting(matrix, n_partitions=5)

    def test_rejects_n_partitions_below_two(self) -> None:
        matrix = pd.DataFrame(np.random.default_rng(0).normal(size=(60, 5)))
        with pytest.raises(ValueError, match=">= 2"):
            probability_of_backtest_overfitting(matrix, n_partitions=0)

    def test_rejects_uneven_block_split(self) -> None:
        matrix = pd.DataFrame(np.random.default_rng(0).normal(size=(61, 5)))
        with pytest.raises(ValueError, match="evenly divisible"):
            probability_of_backtest_overfitting(matrix, n_partitions=6)

    def test_rejects_fewer_than_two_trials(self) -> None:
        matrix = pd.DataFrame(np.random.default_rng(0).normal(size=(60, 1)))
        with pytest.raises(ValueError, match="at least 2 trials"):
            probability_of_backtest_overfitting(matrix, n_partitions=6)

    def test_n_combinations_matches_binomial_coefficient(self) -> None:
        # C(6, 3) = 20
        matrix = pd.DataFrame(np.random.default_rng(0).normal(size=(60, 4)))
        result = probability_of_backtest_overfitting(matrix, n_partitions=6)
        assert result.n_combinations == 20
        assert len(result.logits) == 20

    def test_probability_is_bounded(self) -> None:
        matrix = pd.DataFrame(np.random.default_rng(1).normal(size=(120, 8)))
        result = probability_of_backtest_overfitting(matrix, n_partitions=6)
        assert 0.0 <= result.probability_of_backtest_overfitting <= 1.0

    def test_consistently_dominant_trial_gives_low_pbo(self) -> None:
        # One trial has a real, consistent edge in every block; the rest are
        # pure noise - the in-sample winner should usually be that trial,
        # and it should hold up out-of-sample too.
        rng = np.random.default_rng(42)
        skilled = rng.normal(0.02, 0.05, 480)
        noise = rng.normal(0.0, 0.05, size=(480, 19))
        matrix = pd.DataFrame(np.column_stack([skilled, noise]))
        result = probability_of_backtest_overfitting(matrix, n_partitions=16)
        assert result.probability_of_backtest_overfitting < 0.1

    def test_pure_noise_averages_close_to_one_half(self) -> None:
        # No trial has any real edge anywhere - across many independent
        # draws, "the best in-sample trial" should be right out-of-sample
        # about as often as it's wrong, so PBO should center near 0.5.
        values = []
        for seed in range(15):
            rng = np.random.default_rng(seed)
            matrix = pd.DataFrame(rng.normal(0.0, 0.05, size=(240, 10)))
            result = probability_of_backtest_overfitting(matrix, n_partitions=8)
            values.append(result.probability_of_backtest_overfitting)
        assert np.mean(values) == pytest.approx(0.5, abs=0.15)

    def test_default_metric_matches_pooled_mean_exactly(self) -> None:
        # The per-block-then-averaged fast path must be numerically exact
        # for the default (mean) metric, not just an approximation - mean
        # is linear, so length-weighted averaging of equal-size block means
        # equals the mean over the pooled data.
        rng = np.random.default_rng(3)
        matrix = pd.DataFrame(rng.normal(size=(48, 6)))
        fast = probability_of_backtest_overfitting(matrix, n_partitions=4)

        # Brute-force recomputation via direct concatenation, for one split,
        # to confirm the shortcut agrees with the literal definition.
        from itertools import combinations as _combinations

        block_size = 48 // 4
        blocks = [matrix.iloc[i * block_size : (i + 1) * block_size] for i in range(4)]
        train_ids = next(_combinations(range(4), 2))
        test_ids = [i for i in range(4) if i not in train_ids]
        train = pd.concat([blocks[i] for i in train_ids], axis=0)
        test = pd.concat([blocks[i] for i in test_ids], axis=0)
        expected_best = int(train.mean(axis=0).to_numpy().argmax())
        expected_rank = float(test.mean(axis=0).rank(method="average").iloc[expected_best])

        # Recover the same split's rank from the fast path by reproducing
        # its logit and inverting the omega transform.
        omega = 1 / (1 + np.exp(-fast.logits[0]))
        recovered_rank = omega * (6 + 1)
        assert recovered_rank == pytest.approx(expected_rank, abs=1e-6)

    def test_custom_metric_fn_is_applied_per_block(self) -> None:
        matrix = pd.DataFrame(np.random.default_rng(9).normal(size=(60, 6)))
        result = probability_of_backtest_overfitting(
            matrix, n_partitions=6, metric_fn=lambda s: float(s.std())
        )
        assert 0.0 <= result.probability_of_backtest_overfitting <= 1.0
