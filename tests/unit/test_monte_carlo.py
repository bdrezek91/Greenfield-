"""Monte Carlo simulation must match hand-computable results on deterministic
trade sequences, and be reproducible with a seed on stochastic ones.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from src.analytics.monte_carlo import _wilson_upper_bound, run_monte_carlo


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


def test_wilson_upper_bound_at_zero_events_is_close_to_rule_of_three() -> None:
    # Classic rule-of-three approximation: ~3/n for a 95% bound at k=0.
    bound = _wilson_upper_bound(0, 10_000)
    assert 0.0002 < bound < 0.0005


def test_wilson_upper_bound_zero_trials_is_nan() -> None:
    assert _wilson_upper_bound(0, 0) != _wilson_upper_bound(0, 0)  # nan


def test_wilson_upper_bound_is_at_least_the_point_estimate() -> None:
    for k, n in [(0, 100), (5, 100), (50, 100), (100, 100)]:
        assert _wilson_upper_bound(k, n) >= k / n - 1e-9


def test_summary_reports_risk_of_ruin_upper_bound_when_never_observed() -> None:
    trades = pd.Series([100.0] * 20)  # all-winning -> zero observed ruin events
    result = run_monte_carlo(trades, n_simulations=5000, starting_equity=1000.0, seed=9)
    summary = result.summary()
    assert summary["risk_of_ruin"] == 0.0
    assert summary["risk_of_ruin_events"] == 0
    assert summary["risk_of_ruin_upper_bound_ci95"] > 0.0


def test_block_bootstrap_reuses_only_original_values() -> None:
    trades = pd.Series([1.0, 2.0, 3.0, 4.0, 5.0, -1.0, -2.0])
    result = run_monte_carlo(
        trades, n_simulations=200, block_size=3, starting_equity=1000.0, seed=10
    )
    assert result.n_trades == len(trades)
    assert result.block_size == 3
    # Every simulated total return must be an achievable sum of *some*
    # multiset of the original trade values, never an invented number -
    # spot-check via the return bounds: no simulation can exceed "all trades
    # were the largest value" or fall below "all trades were the smallest".
    max_possible = trades.max() * len(trades) / 1000.0
    min_possible = trades.min() * len(trades) / 1000.0
    assert np.all(result.total_return_pct <= max_possible + 1e-9)
    assert np.all(result.total_return_pct >= min_possible - 1e-9)


def test_block_bootstrap_reproducible_with_seed() -> None:
    trades = pd.Series(np.random.default_rng(11).normal(10, 50, size=30))
    a = run_monte_carlo(trades, n_simulations=500, block_size=5, seed=42)
    b = run_monte_carlo(trades, n_simulations=500, block_size=5, seed=42)
    np.testing.assert_array_equal(a.total_return_pct, b.total_return_pct)


def test_block_bootstrap_rejects_block_size_below_one() -> None:
    trades = pd.Series([1.0, 2.0, 3.0])
    with pytest.raises(ValueError, match="block_size"):
        run_monte_carlo(trades, n_simulations=10, block_size=0)
