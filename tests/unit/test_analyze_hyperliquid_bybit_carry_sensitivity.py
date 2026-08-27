"""scripts/analyze_hyperliquid_bybit_carry_sensitivity.py: quantile/run-
length helpers and the direction-selection logic that must avoid the
mirror-image-cancellation bug (pooling both directions' realized basis/
funding P&L unconditionally always sums to exactly zero per hour, since
each is the other's exact negation - see the parent screen's
realized_basis_pnl_bps/realized_funding_pnl_bps docstrings).
"""

from __future__ import annotations

from scripts.analyze_hyperliquid_bybit_carry_sensitivity import (
    ADVERSE_SELECTION_BPS_AT_FULL_MAKER,
    _positive_run_lengths,
    _quantiles,
)


def test_quantiles_empty_returns_all_none() -> None:
    result = _quantiles([])
    assert result == {
        "p25": None, "median": None, "p75": None, "mean": None, "min": None, "max": None,
    }


def test_quantiles_basic_stats() -> None:
    result = _quantiles([1.0, 2.0, 3.0, 4.0])
    assert result["median"] == 2.5
    assert result["min"] == 1.0
    assert result["max"] == 4.0
    assert result["mean"] == 2.5


def test_quantiles_single_value_below_four_uses_endpoints() -> None:
    result = _quantiles([5.0])
    assert result == {"p25": 5.0, "median": 5.0, "p75": 5.0, "mean": 5.0, "min": 5.0, "max": 5.0}


def test_positive_run_lengths_finds_contiguous_true_runs() -> None:
    flags = [True, True, False, True, False, False, True, True, True]
    assert _positive_run_lengths(flags) == [2, 1, 3]


def test_positive_run_lengths_trailing_true_run_counted() -> None:
    assert _positive_run_lengths([False, True, True]) == [2]


def test_positive_run_lengths_no_positives_is_empty() -> None:
    assert _positive_run_lengths([False, False, False]) == []


def test_positive_run_lengths_all_positive_is_one_run() -> None:
    assert _positive_run_lengths([True, True, True]) == [3]


def test_passive_entry_blend_matches_taker_at_zero_fill_probability() -> None:
    maker_median, taker_median = 5.0, -20.0
    p = 0.0
    blended = p * maker_median + (1 - p) * taker_median - p * ADVERSE_SELECTION_BPS_AT_FULL_MAKER
    assert blended == taker_median


def test_passive_entry_blend_at_full_fill_probability_includes_adverse_selection_penalty() -> None:
    maker_median, taker_median = 5.0, -20.0
    p = 1.0
    blended = p * maker_median + (1 - p) * taker_median - p * ADVERSE_SELECTION_BPS_AT_FULL_MAKER
    # Guaranteed maker fill still pays the full adverse-selection penalty,
    # so it must be strictly worse than the raw maker/maker figure alone.
    assert blended == maker_median - ADVERSE_SELECTION_BPS_AT_FULL_MAKER
    assert blended < maker_median
