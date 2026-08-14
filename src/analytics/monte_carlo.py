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
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd


@dataclass
class MonteCarloResult:
    n_simulations: int
    n_trades: int
    starting_equity: float
    ruin_threshold: float
    total_return_pct: np.ndarray
    max_drawdown_pct: np.ndarray
    longest_losing_streak: np.ndarray
    risk_of_ruin: float

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
            "risk_of_ruin": self.risk_of_ruin,
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
) -> MonteCarloResult:
    """Bootstrap `trade_pnls` (one value per closed trade, in quote currency)
    into `n_simulations` alternate trade orderings/compositions and compute
    the distribution of outcomes. `ruin_threshold` is a fraction (0.5 = a
    50% drawdown from any prior peak counts as ruin).
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
            total_return_pct=empty,
            max_drawdown_pct=empty,
            longest_losing_streak=empty,
            risk_of_ruin=float("nan"),
        )

    rng = np.random.default_rng(seed)
    sample_idx = rng.integers(0, n_trades, size=(n_simulations, n_trades))
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

    risk_of_ruin = float(np.mean(max_drawdown_pct <= -abs(ruin_threshold)))

    return MonteCarloResult(
        n_simulations=n_simulations,
        n_trades=n_trades,
        starting_equity=starting_equity,
        ruin_threshold=ruin_threshold,
        total_return_pct=total_return_pct,
        max_drawdown_pct=max_drawdown_pct,
        longest_losing_streak=longest_losing_streak,
        risk_of_ruin=risk_of_ruin,
    )
