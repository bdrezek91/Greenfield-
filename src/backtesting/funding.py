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
    total = 0.0
    rate = float(assumptions.rate_per_interval)
    for row in positions.itertuples():
        events = funding_timestamps(row.ts_opened, row.ts_closed, assumptions)
        notional = row.quantity * row.avg_px_open
        total += len(events) * notional * rate
    return total
