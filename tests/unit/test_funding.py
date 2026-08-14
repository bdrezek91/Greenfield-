"""Funding cost approximation: correct settlement-count and sign conventions."""

from decimal import Decimal

import pandas as pd
import pytest

from src.backtesting.funding import FundingAssumptions, estimate_funding_cost, funding_timestamps


def test_funding_timestamps_within_one_day() -> None:
    start = pd.Timestamp("2024-01-01T00:00:00", tz="UTC")
    end = pd.Timestamp("2024-01-01T23:59:59", tz="UTC")
    ts = funding_timestamps(start, end, FundingAssumptions())
    assert list(ts.hour) == [0, 8, 16]


def test_funding_timestamps_excludes_out_of_range_edges() -> None:
    start = pd.Timestamp("2024-01-01T01:00:00", tz="UTC")
    end = pd.Timestamp("2024-01-01T08:00:00", tz="UTC")
    ts = funding_timestamps(start, end, FundingAssumptions())
    assert list(ts.hour) == [8]


def test_funding_timestamps_requires_tz_aware() -> None:
    start = pd.Timestamp("2024-01-01")
    end = pd.Timestamp("2024-01-02")
    with pytest.raises(ValueError):
        funding_timestamps(start, end, FundingAssumptions())


def test_estimate_funding_cost_empty_positions_is_zero() -> None:
    assert estimate_funding_cost(pd.DataFrame()) == 0.0


def test_long_position_pays_positive_funding() -> None:
    positions = pd.DataFrame(
        {
            "ts_opened": [pd.Timestamp("2024-01-01T00:00:00", tz="UTC")],
            "ts_closed": [pd.Timestamp("2024-01-01T09:00:00", tz="UTC")],
            "avg_px_open": [50_000.0],
            "quantity": [1.0],  # long
        }
    )
    assumptions = FundingAssumptions(rate_per_interval=Decimal("0.0001"))
    cost = estimate_funding_cost(positions, assumptions)
    # Held through 00:00 and 08:00 settlements -> 2 events.
    assert cost == pytest.approx(2 * 50_000.0 * 0.0001)


def test_short_position_has_opposite_sign_to_long() -> None:
    base = {
        "ts_opened": [pd.Timestamp("2024-01-01T00:00:00", tz="UTC")],
        "ts_closed": [pd.Timestamp("2024-01-01T00:00:00", tz="UTC")],
        "avg_px_open": [50_000.0],
    }
    long_cost = estimate_funding_cost(pd.DataFrame({**base, "quantity": [1.0]}))
    short_cost = estimate_funding_cost(pd.DataFrame({**base, "quantity": [-1.0]}))
    assert long_cost == -short_cost


def test_multiple_positions_sum() -> None:
    positions = pd.DataFrame(
        {
            "ts_opened": [pd.Timestamp("2024-01-01T00:00:00", tz="UTC")] * 2,
            "ts_closed": [pd.Timestamp("2024-01-01T00:00:00", tz="UTC")] * 2,
            "avg_px_open": [50_000.0, 3_000.0],
            "quantity": [1.0, 2.0],
        }
    )
    assumptions = FundingAssumptions(rate_per_interval=Decimal("0.0001"))
    expected = (50_000.0 * 1.0 + 3_000.0 * 2.0) * 0.0001
    assert estimate_funding_cost(positions, assumptions) == pytest.approx(expected)
