"""Timeframe -> periods-per-year mapping (docs/AUTONOMOUS_RESEARCH_AUDIT.md finding M1)."""

from __future__ import annotations

import math

import pytest

from src.backtesting.annualization import (
    TIMEFRAME_PERIODS_PER_YEAR,
    periods_per_year_for_timeframe,
    resolve_periods_per_year,
)


@pytest.mark.parametrize(
    "timeframe,expected",
    [
        ("1m", 365.25 * 24 * 60),
        ("5m", 365.25 * 24 * 12),
        ("15m", 365.25 * 24 * 4),
        ("1h", 365.25 * 24),
        ("4h", 365.25 * 6),
        ("1d", 365.25),
    ],
)
def test_periods_per_year_for_timeframe(timeframe: str, expected: float) -> None:
    assert periods_per_year_for_timeframe(timeframe) == pytest.approx(expected)


def test_unknown_timeframe_raises_rather_than_silently_defaulting() -> None:
    with pytest.raises(ValueError, match="no periods-per-year mapping"):
        periods_per_year_for_timeframe("3h")


def test_all_mapped_timeframes_are_distinct_and_decreasing_with_bar_length() -> None:
    ordered = [TIMEFRAME_PERIODS_PER_YEAR[tf] for tf in ("1m", "5m", "15m", "1h", "4h", "1d")]
    assert ordered == sorted(ordered, reverse=True)


def test_resolve_uses_timeframe_default_when_no_override() -> None:
    value, source = resolve_periods_per_year("4h", None)
    assert value == pytest.approx(365.25 * 6)
    assert source == "timeframe_default"


def test_resolve_records_explicit_override() -> None:
    value, source = resolve_periods_per_year("4h", 12345.0)
    assert value == 12345.0
    assert source == "override"


def test_hourly_default_mis_annualizes_4h_and_1d_sharpe_by_a_known_factor() -> None:
    """Reproduces the exact bug: scripts previously defaulted to the 1h
    factor regardless of --timeframe. Sharpe scales with sqrt(periods_per_year),
    so a Sharpe computed with the wrong (hourly) factor on 4h/1d data is off
    by a fixed, precisely computable multiple - this is the basis for the
    corrected momentum BTCUSDT 4h / volatility_expansion 1d recomputation in
    docs/AUTONOMOUS_RESEARCH_AUDIT.md.
    """
    wrong_default = 365.25 * 24  # what scripts used to hardcode regardless of timeframe
    correct_4h = periods_per_year_for_timeframe("4h")
    correct_1d = periods_per_year_for_timeframe("1d")

    # 4h Sharpe computed with the hourly default was too high by exactly 2x.
    assert math.sqrt(wrong_default) / math.sqrt(correct_4h) == pytest.approx(2.0)
    # 1d Sharpe computed with the hourly default was too high by ~4.9x.
    assert math.sqrt(wrong_default) / math.sqrt(correct_1d) == pytest.approx(
        math.sqrt(24), rel=1e-9
    )
