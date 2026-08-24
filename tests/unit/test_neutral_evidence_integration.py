"""Real DERIVATIVES + CROSS_MARKET evidence (Cycles 42, 44) feeding a real
evaluate_neutral_opportunity call (Cycle 50) - closes the specific gap
docs/GREENFIELD_V2_MASTER_PLAN.md's Phase 7 checkpoint names explicitly
("live portfolio wiring and Neutral/Arbitrage engine remain TARGET
STATE"). Unlike the Directional Engine (Cycles 42-47, which needed six
NEW evidence-scoring rules), evaluate_neutral_opportunity's own
`_rejection_reason` already REQUIRES exactly
{ConfirmationFamily.DERIVATIVES, ConfirmationFamily.CROSS_MARKET} with
`effective_score >= minimum_evidence_strength` - both evidence producers
this test uses already exist and are already validated end-to-end
elsewhere (tests/unit/test_derivatives_evidence.py,
tests/unit/test_cross_market_evidence.py). This is a purely mechanical
wiring test, not a new scoring rule.

Every other input (costs, inventory, stress bounds, execution policy) is
caller-supplied OPERATIONAL state (venue health, margin, borrow
availability) - not something derived from market evidence, so this
test uses realistic placeholder values, the same convention
tests/unit/test_neutral_engine.py's own fixtures already use.
"""

from __future__ import annotations

from datetime import timedelta

import numpy as np
import pandas as pd

from src.engines.contracts import (
    ConfirmationFamily,
    DataQualityStatus,
    EngineGateState,
    LegSide,
    NumericRange,
    SetupAction,
    SetupLeg,
)
from src.engines.cross_market_evidence import cross_market_family_evidence
from src.engines.derivatives_evidence import derivatives_family_evidence
from src.engines.neutral import (
    LegExecutionPolicy,
    NeutralCostBreakdown,
    NeutralEngineConfig,
    NeutralInventoryState,
    NeutralMechanism,
    NeutralOpportunityRequest,
    NeutralStressBounds,
    evaluate_neutral_opportunity,
)
from src.features.cross_market import cross_market_context_frame
from src.features.derivatives import derivatives_context_frame

_AS_OF = pd.Timestamp("2024-01-02T00:00:00Z")


def _derivatives_evidence():
    ts = pd.date_range(end=_AS_OF, periods=25, freq="1h", tz="UTC")
    rng = np.random.default_rng(0)
    mark_price = 100.0 + rng.normal(0, 0.05, size=25)
    oi = 1_000.0 + rng.normal(0, 1.0, size=25)
    mark_price[-1] = mark_price[-2] * 1.05
    oi[-1] = oi[-2] * 1.05
    raw = pd.DataFrame(
        {
            "timestamp": ts,
            "max_source_timestamp": ts,
            "mark_price": mark_price,
            "index_price": mark_price,
            "open_interest": oi,
            "funding_rate": 0.0001,
        }
    )
    return derivatives_family_evidence(derivatives_context_frame(raw, rolling_window=10))


def _cross_market_evidence():
    ts = pd.date_range(end=_AS_OF, periods=30, freq="1h", tz="UTC")
    rng = np.random.default_rng(2)
    base_moves = rng.normal(0, 0.3, size=30)
    prices = {
        "BTC": 100 + np.cumsum(base_moves + rng.normal(0, 0.05, size=30)),
        "ETH": 50 + np.cumsum(base_moves + rng.normal(0, 0.05, size=30)),
        "SOL": 20 + np.cumsum(base_moves + rng.normal(0, 0.05, size=30)),
    }
    for asset in prices:
        prices[asset][-1] = prices[asset][-2] + (3.0 if asset == "BTC" else -1.0)
    rows = []
    for index, timestamp in enumerate(ts):
        for asset, series in prices.items():
            spot = float(series[index])
            rows.append(
                {
                    "timestamp": timestamp,
                    "max_source_timestamp": timestamp,
                    "asset": asset,
                    "spot_price": spot,
                    "perpetual_price": spot * 1.0005,
                }
            )
    panel = cross_market_context_frame(pd.DataFrame(rows), rolling_window=5)
    btc_only = panel[panel["asset"] == "BTC"].drop(columns="asset").reset_index(drop=True)
    return cross_market_family_evidence(btc_only)


def _costs() -> NeutralCostBreakdown:
    return NeutralCostBreakdown(
        fees_bps=NumericRange(2, 3, 4),
        spread_bps=NumericRange(2, 3, 4),
        slippage_bps=NumericRange(2, 3, 5),
        funding_bps=NumericRange(0, 1, 2),
        borrow_bps=NumericRange(0, 0, 1),
        transfer_bps=NumericRange(0, 0, 0),
        orphan_hedge_bps=NumericRange(1, 2, 4),
    )


def _gates() -> EngineGateState:
    return EngineGateState(
        kill_switch_active=False,
        operational_healthy=True,
        promotion_eligible=True,
        promotion_state="RESEARCH",
        risk_approved=True,
        risk_reason="approved",
    )


def test_real_derivatives_and_cross_market_evidence_approve_a_neutral_opportunity() -> None:
    derivatives_evidence = _derivatives_evidence()
    cross_market_evidence = _cross_market_evidence()
    assert derivatives_evidence is not None
    assert cross_market_evidence is not None
    assert derivatives_evidence.family == ConfirmationFamily.DERIVATIVES
    assert cross_market_evidence.family == ConfirmationFamily.CROSS_MARKET
    # Both must clear the engine's own minimum_evidence_strength (0.25 by
    # default) on effective_score = score * confidence * quality - this
    # is the real gate evaluate_neutral_opportunity itself enforces, not
    # something this test relaxes.
    assert derivatives_evidence.effective_score >= 0.25
    assert cross_market_evidence.effective_score >= 0.25

    latest_source = max(
        derivatives_evidence.max_source_timestamp_utc,
        cross_market_evidence.max_source_timestamp_utc,
    )
    decision_time = latest_source + timedelta(seconds=1)

    request = NeutralOpportunityRequest(
        mechanism=NeutralMechanism.CROSS_EXCHANGE_FUNDING,
        symbol="BTCUSDT",
        long_venue="bybit",
        short_venue="okx",
        decision_timestamp_utc=decision_time,
        data_cutoff_utc=decision_time,
        horizon="next-funding-window",
        evidence=(derivatives_evidence, cross_market_evidence),
        regimes=(("liquidity", "LIQUID"), ("cross_market", "NEUTRAL")),
        expected_gross_edge_bps=NumericRange(40, 60, 80),
        costs=_costs(),
        capacity_notional=100_000,
        data_quality_status=DataQualityStatus.PASS,
        model_version="neutral-evidence-v1",
        feature_version="gold-v1",
        inventory=NeutralInventoryState(
            long_leg_available=True,
            short_leg_available=True,
            short_borrow_required=False,
            short_borrow_confirmed=False,
            transfer_required=False,
            prefunded_inventory=True,
            long_venue_healthy=True,
            short_venue_healthy=True,
        ),
        stresses=NeutralStressBounds(
            one_leg_loss_bps=40,
            venue_outage_loss_bps=60,
            liquidation_stress_loss_bps=80,
            margin_buffer_bps=1_500,
            liquidation_distance_bps=2_500,
        ),
        execution_policy=LegExecutionPolicy.HEDGE_ON_PARTIAL,
        maximum_unhedged_seconds=2,
        entry_condition="both executable quotes cover adverse all-in costs",
        invalidation="net basis no longer positive",
        hedge_logic="cancel or hedge orphan leg within two seconds",
        gates=_gates(),
    )
    # maximum_data_age_seconds widened for the same reason as
    # tests/unit/test_full_evidence_integration.py: the two synthetic
    # fixtures have different natural bar granularities, so their real
    # timestamps land minutes apart, not the same instant.
    config = NeutralEngineConfig(maximum_data_age_seconds=10_000_000.0)

    decision = evaluate_neutral_opportunity(request, config)

    assert decision.action == SetupAction.ARBITRAGE
    assert decision.legs == (
        SetupLeg("BTCUSDT", "bybit", LegSide.BUY),
        SetupLeg("BTCUSDT", "okx", LegSide.SELL),
    )
    assert decision.reason_codes == ("BOUNDED_CROSS_EXCHANGE_FUNDING_APPROVED",)
