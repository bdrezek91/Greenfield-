"""Point-in-time executable quote adapter for cross-exchange funding research."""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import UTC, datetime

from src.engines.contracts import NumericRange


class NeutralMarketDataError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class ExecutablePerpetualQuote:
    venue: str
    symbol: str
    bid: float
    ask: float
    funding_rate_per_period: float
    executable_capacity_notional: float
    received_at_utc: datetime

    def __post_init__(self) -> None:
        values = (self.bid, self.ask, self.funding_rate_per_period,
                  self.executable_capacity_notional)
        if not self.venue.strip() or not self.symbol.strip():
            raise NeutralMarketDataError("quote requires venue and symbol")
        if any(not math.isfinite(value) for value in values):
            raise NeutralMarketDataError("quote values must be finite")
        if self.bid <= 0 or self.ask < self.bid or self.executable_capacity_notional < 0:
            raise NeutralMarketDataError("invalid executable quote")
        if self.received_at_utc.tzinfo is None:
            raise NeutralMarketDataError("quote timestamp must be timezone-aware")


@dataclass(frozen=True, slots=True)
class CrossExchangeFundingEdge:
    expected_gross_edge_bps: NumericRange
    capacity_notional: float
    max_source_timestamp_utc: datetime
    entry_basis_bps: float
    funding_differential_bps: float


def derive_cross_exchange_funding_edge(
    long_quote: ExecutablePerpetualQuote,
    short_quote: ExecutablePerpetualQuote,
    *,
    as_of_utc: datetime,
    funding_periods: int,
    model_uncertainty_bps: float,
    maximum_quote_age_seconds: float = 30.0,
) -> CrossExchangeFundingEdge:
    """Derive gross edge from executable entry prices and funding differential.

    Exit costs, fees, slippage and orphan-leg risk remain separate inputs to
    ``NeutralCostBreakdown``; this function never hides them inside gross edge.
    """
    if as_of_utc.tzinfo is None:
        raise NeutralMarketDataError("as_of_utc must be timezone-aware")
    if (
        long_quote.symbol != short_quote.symbol
        or long_quote.venue.lower() == short_quote.venue.lower()
    ):
        raise NeutralMarketDataError("quotes must represent one symbol on distinct venues")
    if funding_periods <= 0 or model_uncertainty_bps < 0 or maximum_quote_age_seconds <= 0:
        raise NeutralMarketDataError("invalid edge-model configuration")
    as_of = as_of_utc.astimezone(UTC)
    for quote in (long_quote, short_quote):
        received = quote.received_at_utc.astimezone(UTC)
        age = (as_of - received).total_seconds()
        if age < 0:
            raise NeutralMarketDataError("future executable quote")
        if age > maximum_quote_age_seconds:
            raise NeutralMarketDataError("stale executable quote")
    reference = ((long_quote.bid + long_quote.ask) + (short_quote.bid + short_quote.ask)) / 4
    entry_basis_bps = (short_quote.bid - long_quote.ask) / reference * 10_000
    funding_differential_bps = (
        short_quote.funding_rate_per_period - long_quote.funding_rate_per_period
    ) * funding_periods * 10_000
    base = entry_basis_bps + funding_differential_bps
    return CrossExchangeFundingEdge(
        expected_gross_edge_bps=NumericRange(
            base - model_uncertainty_bps, base, base + model_uncertainty_bps
        ),
        capacity_notional=min(long_quote.executable_capacity_notional,
                              short_quote.executable_capacity_notional),
        max_source_timestamp_utc=max(long_quote.received_at_utc.astimezone(UTC),
                                     short_quote.received_at_utc.astimezone(UTC)),
        entry_basis_bps=entry_basis_bps,
        funding_differential_bps=funding_differential_bps,
    )
