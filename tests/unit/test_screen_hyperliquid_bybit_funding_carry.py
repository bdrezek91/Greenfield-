"""scripts/screen_hyperliquid_bybit_funding_carry.py: cost-scenario fee
totals must match the documented fee schedule exactly, and the two
direction sign conventions (realized basis P&L, realized funding P&L)
must be genuine mirror images of each other with no double-counting.
"""

from __future__ import annotations

import pytest

from scripts.screen_hyperliquid_bybit_funding_carry import (
    BYBIT_FEES,
    FEE_SCENARIOS,
    HL_FEES,
    basis_bps,
    cost_breakdown,
    realized_basis_pnl_bps,
    realized_funding_pnl_bps,
)

_SPREAD = {"BTC": {"bybit": 0.02, "hyperliquid": 0.2}}


def test_fee_schedule_matches_documented_values() -> None:
    assert BYBIT_FEES == (2.0, 5.5)
    assert HL_FEES == (1.5, 4.5)


@pytest.mark.parametrize(
    ("scenario", "expected_total_fees"),
    [
        ("maker_maker", 2.0 + 1.5 + 2.0 + 1.5),  # 7.0
        ("maker_taker", 2.0 + 1.5 + 5.5 + 4.5),  # 13.5
        ("taker_taker", 5.5 + 4.5 + 5.5 + 4.5),  # 20.0
        ("adverse", 5.5 + 4.5 + 5.5 + 4.5),  # 20.0, same fees as taker_taker
    ],
)
def test_cost_breakdown_fee_totals_match_schedule(
    scenario: str, expected_total_fees: float
) -> None:
    costs = cost_breakdown(scenario, "BTC", _SPREAD)
    assert costs.fees_bps.low == costs.fees_bps.base == costs.fees_bps.high == expected_total_fees


def test_adverse_scenario_widens_slippage_not_fees() -> None:
    taker = cost_breakdown("taker_taker", "BTC", _SPREAD)
    adverse = cost_breakdown("adverse", "BTC", _SPREAD)
    assert adverse.fees_bps == taker.fees_bps
    assert adverse.slippage_bps.base > taker.slippage_bps.base
    assert adverse.slippage_bps.high > taker.slippage_bps.high


def test_funding_bps_is_zero_to_avoid_double_counting_gross_edge() -> None:
    # Funding differential is already inside expected_gross_edge_bps
    # (derive_cross_exchange_funding_edge) - see module docstring.
    for scenario in FEE_SCENARIOS:
        costs = cost_breakdown(scenario, "BTC", _SPREAD)
        assert costs.funding_bps.low == costs.funding_bps.base == costs.funding_bps.high == 0.0
        assert costs.borrow_bps.base == 0.0
        assert costs.transfer_bps.base == 0.0


def test_basis_bps_sign_positive_means_bybit_above_hyperliquid() -> None:
    assert basis_bps(hl_price=100.0, bybit_price=100.1) > 0
    assert basis_bps(hl_price=100.1, bybit_price=100.0) < 0
    assert basis_bps(hl_price=100.0, bybit_price=100.0) == 0.0


def test_realized_basis_pnl_directions_are_mirror_images() -> None:
    entry_basis = 1.0
    exit_basis = 3.0  # basis widened in bybit's favor
    long_bybit = realized_basis_pnl_bps("long_bybit_short_hl", entry_basis, exit_basis)
    long_hl = realized_basis_pnl_bps("long_hl_short_bybit", entry_basis, exit_basis)
    assert long_bybit == pytest.approx(2.0)  # bybit rose relative to hl - long bybit profits
    assert long_hl == pytest.approx(-2.0)
    assert long_bybit == -long_hl


def test_realized_basis_pnl_matches_direct_price_leg_calculation() -> None:
    # Independent derivation: P&L = (bybit_exit - bybit_entry) + (hl_entry - hl_exit)
    # for long_bybit_short_hl, expressed directly in price terms (not via
    # basis_bps at all) - must agree with the bps-normalized shortcut.
    # exit_basis - entry_basis only equals true price-leg P&L/mid exactly
    # when the mid price used for normalization is constant - basis_bps
    # recomputes its own mid at both entry and exit, so a REALISTIC
    # (small, sub-1%) hourly price move is used here to keep that
    # normalization drift negligible relative to the tolerance below;
    # test_realized_basis_pnl_directions_are_mirror_images above already
    # covers the function's sign convention exactly, with no such drift.
    hl_entry, bybit_entry = 100.00, 100.05
    hl_exit, bybit_exit = 99.98, 100.03
    mid_entry = (hl_entry + bybit_entry) / 2
    mid_exit = (hl_exit + bybit_exit) / 2
    entry_basis = (bybit_entry - hl_entry) / mid_entry * 10_000
    exit_basis = (bybit_exit - hl_exit) / mid_exit * 10_000

    price_leg_pnl_dollars = (bybit_exit - bybit_entry) + (hl_entry - hl_exit)
    # Compare in bps terms using the same mid-price normalization the
    # function itself uses at entry (a reasonable, consistent scale).
    price_leg_pnl_bps = price_leg_pnl_dollars / mid_entry * 10_000

    computed = realized_basis_pnl_bps("long_bybit_short_hl", entry_basis, exit_basis)
    assert computed == pytest.approx(price_leg_pnl_bps, abs=0.01)


def test_realized_funding_pnl_long_bybit_short_hl() -> None:
    # long_bybit_short_hl: pay bybit's funding (long leg), receive hl's
    # (short leg). Positive hl funding = we receive; positive bybit
    # funding = we pay.
    pnl = realized_funding_pnl_bps(
        "long_bybit_short_hl", hl_funding_sum_bps=5.0, bybit_funding_sum_bps=2.0
    )
    assert pnl == pytest.approx(3.0)  # net receiver


def test_realized_funding_pnl_long_hl_short_bybit_is_the_mirror() -> None:
    pnl = realized_funding_pnl_bps(
        "long_hl_short_bybit", hl_funding_sum_bps=5.0, bybit_funding_sum_bps=2.0
    )
    assert pnl == pytest.approx(-3.0)
    mirror = realized_funding_pnl_bps(
        "long_bybit_short_hl", hl_funding_sum_bps=5.0, bybit_funding_sum_bps=2.0
    )
    assert pnl == -mirror


def test_realized_funding_pnl_zero_differential_is_zero_regardless_of_direction() -> None:
    for direction in ("long_bybit_short_hl", "long_hl_short_bybit"):
        assert realized_funding_pnl_bps(
            direction, hl_funding_sum_bps=4.0, bybit_funding_sum_bps=4.0
        ) == pytest.approx(0.0)
