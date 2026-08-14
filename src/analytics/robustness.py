"""Multiple-testing / overfitting diagnostics.

Roadmap (docs/RESEARCH_METHODOLOGY.md section on multiple testing):
bootstrap and Deflated Sharpe Ratio (this module, Phases 4/6), Probability
of Backtest Overfitting (this module, below) - White's Reality Check
remains a future addition as experiment volume grows.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from itertools import combinations

import numpy as np
import pandas as pd
from scipy import stats


def bootstrap_metric(
    returns: pd.Series,
    metric_fn: Callable[[pd.Series], float],
    n_iterations: int = 10_000,
    seed: int | None = None,
) -> np.ndarray:
    """Resample `returns` with replacement `n_iterations` times and apply `metric_fn`
    to each resample, for an arbitrary caller-supplied metric. The full
    distribution is returned so callers can derive confidence intervals or
    other summary statistics.

    For the specific, required-by-section-19 Monte Carlo analysis (return
    distribution, drawdown distribution, risk of ruin, losing-streak
    distribution at 10,000+ simulations), see src/analytics/monte_carlo.py
    instead - it resamples trade sequences and is fully vectorized. This
    function stays as the general-purpose building block for anything a
    fixed `metric_fn` can't express as a vectorized array operation; its
    plain-Python per-iteration loop is fine for occasional use but would be
    a bottleneck at 10,000+ iterations with a nontrivial `metric_fn`.
    """
    rng = np.random.default_rng(seed)
    values = returns.to_numpy()
    n = len(values)
    if n == 0:
        return np.array([])

    results = np.empty(n_iterations)
    for i in range(n_iterations):
        sample = rng.choice(values, size=n, replace=True)
        results[i] = metric_fn(pd.Series(sample))
    return results


def confidence_interval(samples: np.ndarray, alpha: float = 0.05) -> tuple[float, float]:
    """Two-sided (1 - alpha) percentile confidence interval."""
    if len(samples) == 0:
        return (float("nan"), float("nan"))
    lo = float(np.percentile(samples, 100 * alpha / 2))
    hi = float(np.percentile(samples, 100 * (1 - alpha / 2)))
    return lo, hi


@dataclass
class DeflatedSharpeResult:
    """`deflated_sharpe_ratio` is the probability that the true Sharpe ratio
    exceeds the expected maximum achievable by chance across `n_trials`
    independent strategies. Values close to 1 indicate the observed edge is
    unlikely to be a selection artifact; values close to 0.5 or below are a
    red flag.
    """

    observed_sharpe: float
    expected_max_sharpe_under_null: float
    deflated_sharpe_ratio: float


def _expected_max_sharpe(n_trials: int, sharpe_variance: float) -> float:
    """Expected maximum Sharpe ratio across `n_trials` independent trials
    under the null of zero true skill (Bailey & Lopez de Prado, 2014).
    """
    if n_trials <= 1:
        return 0.0
    euler_mascheroni = 0.5772156649
    z_a = stats.norm.ppf(1 - 1 / n_trials)
    z_b = stats.norm.ppf(1 - 1 / (n_trials * np.e))
    return float(
        np.sqrt(sharpe_variance) * ((1 - euler_mascheroni) * z_a + euler_mascheroni * z_b)
    )


def deflated_sharpe_ratio(
    observed_sharpe: float, returns: pd.Series, n_trials: int
) -> DeflatedSharpeResult:
    """Deflated Sharpe Ratio: the probability that `observed_sharpe` reflects
    genuine skill rather than the best result out of `n_trials` strategies
    tested (selection bias), accounting for the return series' skew and
    kurtosis (non-normality inflates the variance of the Sharpe estimator).

    `returns` should be the per-period returns the Sharpe ratio was computed
    from (same period as `observed_sharpe`'s annualization).
    """
    n_obs = len(returns)
    if n_obs < 2:
        return DeflatedSharpeResult(observed_sharpe, float("nan"), float("nan"))

    skew = float(returns.skew())
    kurtosis = float(returns.kurtosis()) + 3.0  # pandas returns *excess* kurtosis

    sharpe_variance = (
        1 - skew * observed_sharpe + ((kurtosis - 1) / 4) * observed_sharpe**2
    ) / (n_obs - 1)
    sr0 = _expected_max_sharpe(n_trials, sharpe_variance)

    denom = np.sqrt(1 - skew * observed_sharpe + ((kurtosis - 1) / 4) * observed_sharpe**2)
    if denom <= 0:
        psr = float("nan")
    else:
        z = (observed_sharpe - sr0) * np.sqrt(n_obs - 1) / denom
        psr = float(stats.norm.cdf(z))

    return DeflatedSharpeResult(
        observed_sharpe=observed_sharpe,
        expected_max_sharpe_under_null=sr0,
        deflated_sharpe_ratio=psr,
    )


@dataclass
class PBOResult:
    """`probability_of_backtest_overfitting` is the fraction of CSCV splits
    in which the trial that looked best in-sample ranked in the bottom
    half out-of-sample - i.e. the fraction of `logits <= 0`. Close to 0.5
    means picking "the best backtest" out of `performance_matrix`'s trials
    is no better than a coin flip at finding real out-of-sample skill;
    close to 0 means the in-sample winner tends to hold up out-of-sample.
    """

    n_combinations: int
    probability_of_backtest_overfitting: float
    logits: np.ndarray


def probability_of_backtest_overfitting(
    performance_matrix: pd.DataFrame,
    n_partitions: int = 16,
    metric_fn: Callable[[pd.Series], float] | None = None,
) -> PBOResult:
    """Combinatorially Symmetric Cross-Validation (Bailey, Borwein, Lopez de
    Prado & Zhu, 2015) - the standard estimator for Probability of Backtest
    Overfitting, per docs/RESEARCH_METHODOLOGY.md's multiple-testing
    section: don't just pick the parameter combination with the best
    backtest metric out of many tried (`n_trials` in
    `deflated_sharpe_ratio`, above) - check whether "the best in-sample
    trial" is actually predictive of anything out-of-sample at all.

    `performance_matrix`: T rows (time periods, in chronological order) x
    N columns (trials - e.g. one column per parameter combination or
    strategy variant backtested over the SAME periods). `metric_fn`
    (default: mean) reduces a trial's per-period values within a block to
    one comparable number; use something like `lambda s: s.mean() /
    s.std()` for a quick per-block Sharpe-style score instead.

    `n_partitions` (S, must be even) splits the T rows into S contiguous,
    equal-size blocks. Every way of choosing S/2 blocks as the "training"
    half - C(S, S/2) combinations, both a split and its complement are
    included, matching the original CSCV algorithm - selects the
    best-in-training trial and records its relative out-of-sample rank as
    a logit; `probability_of_backtest_overfitting` is the fraction of
    those logits that are <= 0 (in-sample winner ranked at or below the
    out-of-sample median).

    `metric_fn` is applied ONCE PER BLOCK PER TRIAL (S x N calls total),
    not once per combination - the paper's own examples use S=16, i.e.
    C(16, 8) = 12,870 combinations, so recomputing a combination's metric
    from scratch per combination (rather than reducing already-computed
    per-block scores) would be needlessly quadratic in practice. This
    means `metric_fn` must be well-defined on a single contiguous block
    (e.g. mean, or std-based Sharpe on that block alone) - it is never
    given the union of a combination's blocks directly. The default
    (`s.mean()`) is combined across a combination's blocks via a length-
    weighted average of the per-block means, exact for a mean; for a
    non-linear custom `metric_fn` (e.g. Sharpe), the combination-level
    score is likewise the length-weighted average of per-block scores -
    an approximation of the metric on the pooled data, standard practice
    for CSCV at this block count and adequate for this diagnostic's
    purpose (ranking trials relative to each other, not an exact metric
    value).

    Raises ValueError if `n_partitions` is odd or < 2, T isn't evenly
    divisible by `n_partitions` (an uneven last block would bias which
    periods count more), or there are fewer than 2 trials to rank.
    """
    if n_partitions < 2:
        raise ValueError("n_partitions must be >= 2")
    if n_partitions % 2 != 0:
        raise ValueError("n_partitions must be even (CSCV splits into training/testing halves)")

    n_periods, n_trials = performance_matrix.shape
    if n_trials < 2:
        raise ValueError("need at least 2 trials to rank")
    if n_periods % n_partitions != 0:
        raise ValueError(
            f"performance_matrix has {n_periods} rows, not evenly divisible by "
            f"n_partitions={n_partitions}"
        )

    metric_fn = metric_fn or (lambda s: float(s.mean()))
    block_size = n_periods // n_partitions
    # One metric_fn call per (block, trial) - S x N total, computed once
    # and reused across every combination below.
    block_scores = np.array(
        [
            [
                metric_fn(performance_matrix.iloc[i * block_size : (i + 1) * block_size, j])
                for j in range(n_trials)
            ]
            for i in range(n_partitions)
        ]
    )  # shape (n_partitions, n_trials)

    half = n_partitions // 2
    all_ids = np.arange(n_partitions)
    logits = []
    for train_ids in combinations(range(n_partitions), half):
        test_ids = [i for i in all_ids if i not in train_ids]

        train_scores = block_scores[list(train_ids)].mean(axis=0)
        best_trial = int(np.argmax(train_scores))

        test_scores = block_scores[test_ids].mean(axis=0)
        rank = float(stats.rankdata(test_scores)[best_trial])  # 1..n_trials, ties averaged
        omega = rank / (n_trials + 1)
        omega = min(max(omega, 1e-9), 1 - 1e-9)  # avoid +/-inf logit at the boundary
        logits.append(float(np.log(omega / (1 - omega))))

    logits_arr = np.array(logits)
    pbo = float(np.mean(logits_arr <= 0))
    return PBOResult(
        n_combinations=len(logits_arr), probability_of_backtest_overfitting=pbo, logits=logits_arr
    )


def flag_isolated_spikes(
    param_values: list[float], metric_values: list[float], spike_ratio: float = 2.0
) -> list[bool]:
    """Flag parameter points that look like overfitting artifacts rather than
    a real edge, per docs/RESEARCH_METHODOLOGY.md section 20: "if a strategy
    only works at RSI=51.382 but not 50 or 52, treat that as a symptom of
    overfitting." A point is flagged when it's a local maximum whose metric
    value exceeds `spike_ratio` times the average of its two immediate
    neighbors - a stable parameter region has no such point, only a smooth
    ridge. Requires ascending, evenly-conceptual `param_values` (the actual
    spacing doesn't matter, only adjacency); the first and last points have
    only one neighbor each and are never flagged. Assumes metric values are
    positive (e.g. Sharpe, profit factor) - a negative or zero neighbor
    average makes the ratio check meaningless, so those points are skipped
    (never flagged) rather than misinterpreted.
    """
    if len(param_values) != len(metric_values):
        raise ValueError("param_values and metric_values must be the same length")

    n = len(metric_values)
    flags = [False] * n
    for i in range(1, n - 1):
        left, center, right = metric_values[i - 1], metric_values[i], metric_values[i + 1]
        neighbor_avg = (left + right) / 2
        if center <= 0 or neighbor_avg <= 0:
            continue
        if center > left and center > right and center > neighbor_avg * spike_ratio:
            flags[i] = True
    return flags
