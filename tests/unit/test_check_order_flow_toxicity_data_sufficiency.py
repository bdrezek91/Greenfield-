"""scripts/check_order_flow_toxicity_data_sufficiency.py: the contiguous-
run finder must find the LONGEST gap-free stretch, not just count total
days present (a preregistered walk-forward with embargo needs continuous
history, not scattered isolated days).
"""

from __future__ import annotations

from scripts.check_order_flow_toxicity_data_sufficiency import _longest_contiguous_run


def test_single_contiguous_run() -> None:
    dates = ["2026-08-22", "2026-08-23", "2026-08-24", "2026-08-25"]
    assert _longest_contiguous_run(dates) == dates


def test_two_runs_picks_the_longer_one() -> None:
    dates = ["2026-08-01", "2026-08-02", "2026-08-10", "2026-08-11", "2026-08-12"]
    assert _longest_contiguous_run(dates) == ["2026-08-10", "2026-08-11", "2026-08-12"]


def test_unsorted_input_is_sorted_first() -> None:
    dates = ["2026-08-24", "2026-08-22", "2026-08-23"]
    assert _longest_contiguous_run(dates) == ["2026-08-22", "2026-08-23", "2026-08-24"]


def test_all_isolated_days_returns_single_day_run() -> None:
    dates = ["2026-08-01", "2026-08-05", "2026-08-10"]
    assert _longest_contiguous_run(dates) == ["2026-08-01"]


def test_empty_input_returns_empty() -> None:
    assert _longest_contiguous_run([]) == []


def test_duplicate_dates_do_not_break_the_run() -> None:
    dates = ["2026-08-22", "2026-08-23", "2026-08-23", "2026-08-24"]
    assert _longest_contiguous_run(dates) == ["2026-08-22", "2026-08-23", "2026-08-24"]
