"""Multiple-testing / overfitting diagnostics.

Roadmap (docs/RESEARCH_METHODOLOGY.md section on multiple testing):
bootstrap and Deflated Sharpe Ratio first (this module), Probability of
Backtest Overfitting and White's Reality Check later as experiment volume
grows.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

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
