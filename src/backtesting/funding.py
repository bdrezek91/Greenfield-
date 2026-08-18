"""Approximate perpetual funding cost as a post-hoc adjustment.

NautilusTrader (as installed here) has no built-in perpetual-funding
simulation module - see docs/PHASE_0_ARCHITECTURE_RESEARCH.md, open research
question 2, and docs/DATA.md's note on Bybit's limited funding rate history.
Rather than fabricate in-engine funding mechanics against an API we can't
verify, this module computes an explicit, documented approximation from a
position's exposure history, to be applied as a cost adjustment on top of a
backtest's PnL. This keeps the assumption visible and swappable instead of
silently baked into the simulation.

Standard perpetual convention: a positive funding rate means longs pay
shorts. Cost is expressed from the position holder's point of view (positive
= cost, negative = credit).
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

import pandas as pd

# Bybit's standard funding settlement times.
DEFAULT_FUNDING_HOURS_UTC: tuple[int, ...] = (0, 8, 16)


@dataclass(frozen=True)
class FundingAssumptions:
    """A recorded, explicit funding assumption - part of an experiment's
    metadata (docs/RESEARCH_METHODOLOGY.md), never a silent default.
    """

    rate_per_interval: Decimal = Decimal("0.0001")  # 0.01%, a commonly cited baseline
    funding_hours_utc: tuple[int, ...] = DEFAULT_FUNDING_HOURS_UTC
    historical_rates: tuple[tuple[int, float], ...] = ()
    multiplier: float = 1.0
    source: str = "constant_assumption"

    @classmethod
    def from_history(
        cls, funding: pd.DataFrame, *, multiplier: float = 1.0
    ) -> FundingAssumptions:
        """Create immutable point-in-time funding assumptions from storage."""
        if funding.empty:
            raise ValueError("historical funding frame is empty")
        ordered = funding.sort_values("timestamp")
        rates = tuple(
            (int(pd.Timestamp(row.timestamp).value), float(row.funding_rate))
            for row in ordered.itertuples()
        )
        return cls(historical_rates=rates, multiplier=multiplier, source="historical_bybit")


def funding_timestamps(
    start: pd.Timestamp, end: pd.Timestamp, assumptions: FundingAssumptions
) -> pd.DatetimeIndex:
    """All funding settlement timestamps in the half-open interval [start, end).

    Half-open so that a position closing exactly at a settlement and the next
    position on the same instrument opening exactly at that same instant are
    never both charged for it: the closing position is not (it didn't hold
    into the settlement), the opening one is. Using a closed interval on both
    ends would double-count that settlement across the two positions.
    """
    if start.tzinfo is None or end.tzinfo is None:
        raise ValueError("start/end must be timezone-aware (UTC)")
    days = pd.date_range(start.floor("D"), end.ceil("D"), freq="D", tz="UTC")
    candidates = pd.DatetimeIndex(
        sorted(
            day + pd.Timedelta(hours=h) for day in days for h in assumptions.funding_hours_utc
        )
    )
    return candidates[(candidates >= start) & (candidates < end)]


def estimate_funding_cost(
    positions: pd.DataFrame, assumptions: FundingAssumptions | None = None
) -> float:
    """Estimate total funding cost across a set of positions.

    `positions` must have one row per position with columns:
        - ts_opened: tz-aware UTC timestamp
        - ts_closed: tz-aware UTC timestamp (use the backtest end for still-open positions)
        - avg_px_open: float, average entry price
        - quantity: float, signed (positive = long, negative = short)

    Returns the total funding cost in quote currency (positive = net cost,
    negative = net credit), summed across every funding settlement the
    position was held through.
    """
    if positions.empty:
        return 0.0

    assumptions = assumptions or FundingAssumptions()
    return sum(cost for _timestamp, cost in funding_cashflows(positions, assumptions))


def funding_cashflows(
    positions: pd.DataFrame, assumptions: FundingAssumptions | None = None
) -> list[tuple[pd.Timestamp, float]]:
    """Return timestamped funding cashflows for per-bar MTM accounting.

    Positive values are costs and negative values are credits. Historical
    Bybit rates are preferred; the explicit constant schedule remains only
    as a fallback for callers without a funding dataset.
    """
    if positions.empty:
        return []
    assumptions = assumptions or FundingAssumptions()
    cashflows: list[tuple[pd.Timestamp, float]] = []
    for row in positions.itertuples():
        notional = row.quantity * row.avg_px_open
        if assumptions.historical_rates:
            opened_ns = int(pd.Timestamp(row.ts_opened).value)
            closed_ns = int(pd.Timestamp(row.ts_closed).value)
            for timestamp_ns, rate in assumptions.historical_rates:
                if opened_ns <= timestamp_ns < closed_ns:
                    cashflows.append(
                        (
                            pd.Timestamp(timestamp_ns, unit="ns", tz="UTC"),
                            notional * rate * assumptions.multiplier,
                        )
                    )
        else:
            rate = float(assumptions.rate_per_interval) * assumptions.multiplier
            for timestamp in funding_timestamps(row.ts_opened, row.ts_closed, assumptions):
                cashflows.append((timestamp, notional * rate))
    return sorted(cashflows, key=lambda item: item[0])
