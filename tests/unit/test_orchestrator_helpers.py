"""Focused tests for orchestrator helpers that don't need the full engine:
resource-budget enforcement, disk-space guard, and the "no LIVE capability
anywhere in src/research/" guarantee.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from src.research.orchestrator import _disk_space_ok, _pbo_partitions, _perturb
from src.research.promotion import STATUSES


def test_disk_space_ok_for_a_reasonable_threshold(tmp_path: Path) -> None:
    assert _disk_space_ok(tmp_path, min_free_mb=1) is True


def test_disk_space_not_ok_for_an_absurd_threshold(tmp_path: Path) -> None:
    assert _disk_space_ok(tmp_path, min_free_mb=10**9) is False


def test_pbo_partitions_even_periods() -> None:
    assert _pbo_partitions(8) == 8


def test_pbo_partitions_odd_periods_drops_one() -> None:
    assert _pbo_partitions(9) == 8


def test_pbo_partitions_too_few_periods_returns_none() -> None:
    assert _pbo_partitions(2) is None
    assert _pbo_partitions(3) is None


def test_perturb_scales_numeric_fields() -> None:
    out = _perturb({"lookback_bars": 20, "threshold": 0.01}, 0.10)
    assert out["lookback_bars"] == 22
    assert out["threshold"] == pytest.approx(0.011)


def test_perturb_never_zeroes_an_int_field() -> None:
    out = _perturb({"lookback_bars": 1}, -0.99)
    assert out["lookback_bars"] >= 1


def test_perturb_leaves_non_numeric_fields_untouched() -> None:
    out = _perturb({"name": "momentum"}, 0.10)
    assert out["name"] == "momentum"


def test_no_live_status_exists_anywhere_in_the_promotion_state_machine() -> None:
    """The promotion state machine's universe stops at PAPER_CHAMPION -
    there is no LIVE-adjacent status the research module could ever reach."""
    assert "LIVE" not in STATUSES
    assert all("LIVE" not in status for status in STATUSES)
