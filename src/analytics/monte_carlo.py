"""Monte Carlo simulation over resampled trade sequences.

Per docs/RESEARCH_METHODOLOGY.md section 19: for strategies that pass basic
validation, run a minimum of 10,000 simulations analyzing the return
distribution, drawdown distribution, risk of ruin, and losing-streak
distribution.

Trades (not equity-curve returns) are resampled with replacement so the
losing-streak and risk-of-ruin statistics reflect trade-level path
dependency - the conventional meaning of those terms in trading system
evaluation. Fully vectorized over simulations (only the O(n_trades) streak
computation loops, over the trade count, not the simulation count) so
10,000+ simulations run in well under a second for realistic trade counts.

Two resampling modes (see docs/AUTONOMOUS_RESEARCH_AUDIT.md M5):
`block_size=None` (default) draws each simulated trade independently with
replacement (IID bootstrap) - correct for the return/drawdown distribution
under an independence assumption, but it destroys any autocorrelation
between consecutive trades (volatility clustering, losing-streak regimes).
Passing `block_size` switches to a circular moving-block bootstrap: each
simulation is built from contiguous, wrapped-around chunks of the ORIGINAL
trade order, which preserves whatever short-range dependency exists between
neighboring trades. Block bootstrap is still just a heuristic approximation
(the true dependency structure isn't known), not a proof of independence
either way - it's strictly better than IID when trades are suspected to be
dependent, never a guarantee of correctness.

`risk_of_ruin` is a point estimate. When zero simulations breach the ruin
threshold, that does NOT mean the true probability is zero - `summary()`
also reports a 95% Wilson-interval upper bound on it, per M5's specific
complaint that a bare `risk_of_ruin=0.0` overstates confidence for the
usual case of a moderate `n_simulations` where zero ruin events were
merely never observed within that many draws.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

_WILSON_Z_95 = 1.959963985


def _wilson_upper_bound(successes: int, trials: int, z: float = _WILSON_Z_95) -> float:
    """Upper bound of a two-sided Wilson score confidence interval for a
    binomial proportion. Reduces to the familiar "rule of three" (~3/n)
    approximation when `successes == 0` and `trials` is reasonably large,
    but stays well-defined (and exact, not an approximation) for any
    successes/trials, unlike the naive Wald interval which is unusable at
    the p=0 boundary.
    """
    if trials == 0:
        return float("nan")
    phat = successes / trials
    denom = 1 + z**2 / trials
    center = (phat + z**2 / (2 * trials)) / denom
    half_width = (z * ((phat * (1 - phat) + z**2 / (4 * trials)) / trials) ** 0.5) / denom
    return min(1.0, center + half_width)


@dataclass
class MonteCarloResult:
    n_simulations: int
    n_trades: int
    starting_equity: float
    ruin_threshold: float
    block_size: int | None
    total_return_pct: np.ndarray
    max_drawdown_pct: np.ndarray
    longest_losing_streak: np.ndarray
    risk_of_ruin: float
    risk_of_ruin_events: int

    def summary(self) -> dict:
        if self.n_trades == 0:
            return {
                "n_simulations": self.n_simulations,
                "n_trades": 0,
                "risk_of_ruin": float("nan"),
            }

        def pct(arr: np.ndarray, q: float) -> float:
            return float(np.percentile(arr, q))

        return {
            "n_simulations": self.n_simulations,
            "n_trades": self.n_trades,
            "block_size": self.block_size,
            "risk_of_ruin": self.risk_of_ruin,
            "risk_of_ruin_events": self.risk_of_ruin_events,
            "risk_of_ruin_upper_bound_ci95": _wilson_upper_bound(
                self.risk_of_ruin_events, self.n_simulations
            ),
            "return_pct_p05": pct(self.total_return_pct, 5),
            "return_pct_p50": pct(self.total_return_pct, 50),
            "return_pct_p95": pct(self.total_return_pct, 95),
            "max_drawdown_pct_p05": pct(self.max_drawdown_pct, 5),
            "max_drawdown_pct_p50": pct(self.max_drawdown_pct, 50),
            "max_drawdown_pct_p95": pct(self.max_drawdown_pct, 95),
            "losing_streak_p50": pct(self.longest_losing_streak, 50),
            "losing_streak_p95": pct(self.longest_losing_streak, 95),
        }


def run_monte_carlo(
    trade_pnls: pd.Series,
    n_simulations: int = 10_000,
    starting_equity: float = 100_000.0,
    ruin_threshold: float = 0.5,
    seed: int | None = None,
    block_size: int | None = None,
) -> MonteCarloResult:
    """Bootstrap `trade_pnls` (one value per closed trade, in quote currency)
    into `n_simulations` alternate trade orderings/compositions and compute
    the distribution of outcomes. `ruin_threshold` is a fraction (0.5 = a
    50% drawdown from any prior peak counts as ruin).

    `block_size=None` (default) is the plain IID bootstrap. Passing a
    `block_size >= 2` switches to a circular moving-block bootstrap that
    resamples contiguous chunks of `trade_pnls` in its ORIGINAL order,
    preserving whatever short-range autocorrelation exists between
    neighboring trades - see the module docstring.
    """
    values = trade_pnls.to_numpy(dtype=float)
    n_trades = len(values)

    if n_trades == 0:
        empty = np.array([])
        return MonteCarloResult(
            n_simulations=n_simulations,
            n_trades=0,
            starting_equity=starting_equity,
            ruin_threshold=ruin_threshold,
            block_size=block_size,
            total_return_pct=empty,
            max_drawdown_pct=empty,
            longest_losing_streak=empty,
            risk_of_ruin=float("nan"),
            risk_of_ruin_events=0,
        )

    rng = np.random.default_rng(seed)
    if block_size is None:
        sample_idx = rng.integers(0, n_trades, size=(n_simulations, n_trades))
    else:
        if block_size < 1:
            raise ValueError(f"block_size must be >= 1, got {block_size}")
        n_blocks = -(-n_trades // block_size)  # ceil division
        block_starts = rng.integers(0, n_trades, size=(n_simulations, n_blocks))
        offsets = np.arange(block_size)
        # Circular: wrap block indices around n_trades so every start point,
        # including ones near the end of the series, yields a full block.
        sample_idx = (block_starts[:, :, None] + offsets[None, None, :]) % n_trades
        sample_idx = sample_idx.reshape(n_simulations, n_blocks * block_size)[:, :n_trades]
    samples = values[sample_idx]  # (n_simulations, n_trades)

    # Prepend the starting balance as t=0 so drawdown accounts for a losing
    # first trade, then compute cumulative equity for the rest of the path.
    equity_paths = starting_equity + np.cumsum(samples, axis=1)
    full_paths = np.concatenate(
        [np.full((n_simulations, 1), starting_equity), equity_paths], axis=1
    )
    running_max = np.maximum.accumulate(full_paths, axis=1)
    drawdowns = full_paths / running_max - 1
    max_drawdown_pct = drawdowns.min(axis=1)

    total_return_pct = (full_paths[:, -1] - starting_equity) / starting_equity

    loss_mask = samples < 0
    streak = np.zeros_like(loss_mask, dtype=np.int64)
    streak[:, 0] = loss_mask[:, 0]
    for j in range(1, n_trades):
        streak[:, j] = (streak[:, j - 1] + 1) * loss_mask[:, j]
    longest_losing_streak = streak.max(axis=1)

    ruin_events = int(np.sum(max_drawdown_pct <= -abs(ruin_threshold)))
    risk_of_ruin = ruin_events / n_simulations

    return MonteCarloResult(
        n_simulations=n_simulations,
        n_trades=n_trades,
        starting_equity=starting_equity,
        ruin_threshold=ruin_threshold,
        block_size=block_size,
        total_return_pct=total_return_pct,
        max_drawdown_pct=max_drawdown_pct,
        longest_losing_streak=longest_losing_streak,
        risk_of_ruin=risk_of_ruin,
        risk_of_ruin_events=ruin_events,
    )
