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
    to each resample. The full distribution is returned so callers can derive
    confidence intervals, risk-of-ruin, drawdown distributions, etc.
    (see docs/RESEARCH_METHODOLOGY.md's Monte Carlo section, fully built out in Phase 7).

    Note: this loop calls `metric_fn` once per iteration in plain Python, which
    is fine at Phase 4's scale but will be a bottleneck once Phase 7 runs this
    at the required 10,000+ simulations with a nontrivial `metric_fn` -
    vectorizing (e.g. resampling all iterations at once and applying `metric_fn`
    over an array axis) should be revisited then.
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
