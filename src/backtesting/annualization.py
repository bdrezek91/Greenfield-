"""Timeframe -> periods-per-year mapping for Sharpe/Sortino/Calmar annualization.

`src.analytics.metrics.compute_equity_metrics` takes `periods_per_year` as a
required parameter and never guesses it - that is correct. The bug this
module fixes lived one layer up: every CLI in `scripts/` defaulted
`periods_per_year` to `365.25 * 24` (an hourly-bar assumption) regardless of
the `--timeframe` actually requested, silently mis-annualizing Sharpe by a
factor of sqrt(hours_per_bar) for anything coarser than 1h (2x too high for
4h, ~4.9x too high for 1d).

This module makes the correct factor the default for a given timeframe and
makes an operator override explicit and recorded, per
docs/RESEARCH_METHODOLOGY.md's reproducibility contract - never a silent
default that could be mistaken for the right one.
"""

from __future__ import annotations

_HOURS_PER_YEAR = 365.25 * 24

TIMEFRAME_PERIODS_PER_YEAR: dict[str, float] = {
    "1m": 365.25 * 24 * 60,
    "5m": 365.25 * 24 * 12,
    "15m": 365.25 * 24 * 4,
    "1h": _HOURS_PER_YEAR,
    "4h": 365.25 * 6,
    "1d": 365.25,
}


def periods_per_year_for_timeframe(timeframe: str) -> float:
    """The correct annualization factor for `timeframe`.

    Raises `ValueError` for an unknown timeframe rather than silently
    falling back to some default - an unrecognized timeframe must stop the
    caller, not produce a plausible-looking but wrong Sharpe.
    """
    try:
        return TIMEFRAME_PERIODS_PER_YEAR[timeframe]
    except KeyError:
        raise ValueError(
            f"no periods-per-year mapping for timeframe {timeframe!r}, "
            f"expected one of {sorted(TIMEFRAME_PERIODS_PER_YEAR)}"
        ) from None


def resolve_periods_per_year(timeframe: str, override: float | None) -> tuple[float, str]:
    """Resolve the periods-per-year to use plus a source label.

    Returns `(value, "override")` if the caller passed an explicit
    `override`, else `(value, "timeframe_default")` derived from
    `timeframe`. The source label is meant to be recorded verbatim in an
    experiment's parameters so a reader never has to guess whether a given
    run used the timeframe-correct default or an operator-chosen value.
    """
    if override is not None:
        return override, "override"
    return periods_per_year_for_timeframe(timeframe), "timeframe_default"
