from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from src.engines.neutral_market import (
    ExecutablePerpetualQuote,
    NeutralMarketDataError,
    derive_cross_exchange_funding_edge,
)

NOW = datetime(2026, 1, 1, tzinfo=UTC)


def _quote(venue: str, bid: float, ask: float, funding: float, *, age: int = 1):
    return ExecutablePerpetualQuote(
        venue, "BTCUSDT", bid, ask, funding, 100_000, NOW - timedelta(seconds=age)
    )


def test_derives_edge_from_executable_prices_and_funding() -> None:
    edge = derive_cross_exchange_funding_edge(
        _quote("bybit", 99.9, 100.0, -0.0005),
        _quote("okx", 100.5, 100.6, 0.0005),
        as_of_utc=NOW,
        funding_periods=1,
        model_uncertainty_bps=10,
    )
    assert edge.entry_basis_bps == pytest.approx(49.87531172)
    assert edge.funding_differential_bps == pytest.approx(10)
    assert edge.expected_gross_edge_bps.base == pytest.approx(59.87531172)
    assert edge.expected_gross_edge_bps.low == pytest.approx(49.87531172)
    assert edge.capacity_notional == 100_000


@pytest.mark.parametrize("age, message", [(-1, "future"), (31, "stale")])
def test_rejects_future_or_stale_quotes(age: int, message: str) -> None:
    with pytest.raises(NeutralMarketDataError, match=message):
        derive_cross_exchange_funding_edge(
            _quote("bybit", 99, 100, 0, age=age),
            _quote("okx", 100, 101, 0, age=age),
            as_of_utc=NOW,
            funding_periods=1,
            model_uncertainty_bps=1,
        )
