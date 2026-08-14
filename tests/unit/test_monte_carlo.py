"""Monte Carlo simulation must match hand-computable results on deterministic
trade sequences, and be reproducible with a seed on stochastic ones.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from src.analytics.monte_carlo import run_monte_carlo


def test_empty_trades_returns_nan_risk_of_ruin() -> None:
    result = run_monte_carlo(pd.Series(dtype=float), n_simulations=100)
    assert result.n_trades == 0
    assert result.total_return_pct.size == 0
    assert result.risk_of_ruin != result.risk_of_ruin  # nan


def test_all_winning_trades_never_lose_or_ruin() -> None:
    # Every resample is still "20 wins of +100" regardless of order.
    trades = pd.Series([100.0] * 20)
    result = run_monte_carlo(trades, n_simulations=500, starting_equity=1000.0, seed=1)

    assert result.n_trades == 20
    expected_return = 20 * 100.0 / 1000.0
    assert np.allclose(result.total_return_pct, expected_return)
    assert np.all(result.longest_losing_streak == 0)
    assert np.all(result.max_drawdown_pct == 0.0)
    assert result.risk_of_ruin == 0.0


def test_all_losing_trades_always_breach_ruin_and_streak_is_full_length() -> None:
    trades = pd.Series([-100.0] * 20)
    result = run_monte_carlo(
        trades, n_simulations=500, starting_equity=1000.0, ruin_threshold=0.5, seed=2
    )

    assert np.all(result.longest_losing_streak == 20)
    assert result.risk_of_ruin == 1.0
    # Every path ends the same way regardless of (irrelevant) resample order.
    assert np.allclose(result.total_return_pct, -2.0)  # -2000 / 1000


def test_reproducible_with_seed() -> None:
    trades = pd.Series(np.random.default_rng(0).normal(10, 50, size=30))
    a = run_monte_carlo(trades, n_simulations=1000, seed=42)
    b = run_monte_carlo(trades, n_simulations=1000, seed=42)

    np.testing.assert_array_equal(a.total_return_pct, b.total_return_pct)
    np.testing.assert_array_equal(a.max_drawdown_pct, b.max_drawdown_pct)
    np.testing.assert_array_equal(a.longest_losing_streak, b.longest_losing_streak)


def test_output_shapes_match_n_simulations() -> None:
    trades = pd.Series([10.0, -5.0, 20.0, -15.0, 8.0])
    result = run_monte_carlo(trades, n_simulations=250, seed=3)

    assert result.total_return_pct.shape == (250,)
    assert result.max_drawdown_pct.shape == (250,)
    assert result.longest_losing_streak.shape == (250,)


def test_max_drawdown_is_never_positive() -> None:
    trades = pd.Series(np.random.default_rng(4).normal(5, 40, size=40))
    result = run_monte_carlo(trades, n_simulations=2000, seed=5)
    assert np.all(result.max_drawdown_pct <= 0)


def test_summary_contains_expected_keys() -> None:
    trades = pd.Series([10.0, -5.0, 20.0, -15.0, 8.0])
    result = run_monte_carlo(trades, n_simulations=200, seed=6)
    summary = result.summary()
    assert summary["n_simulations"] == 200
    assert summary["n_trades"] == 5
    assert "return_pct_p50" in summary
    assert "max_drawdown_pct_p50" in summary
    assert "losing_streak_p95" in summary


def test_summary_empty_trades() -> None:
    result = run_monte_carlo(pd.Series(dtype=float), n_simulations=10)
    summary = result.summary()
    assert summary["n_trades"] == 0


def test_risk_of_ruin_monotonic_in_threshold() -> None:
    trades = pd.Series(np.random.default_rng(7).normal(-2, 30, size=25))
    low = run_monte_carlo(trades, n_simulations=3000, ruin_threshold=0.1, seed=8)
    high = run_monte_carlo(trades, n_simulations=3000, ruin_threshold=0.9, seed=8)
    assert low.risk_of_ruin >= high.risk_of_ruin
