from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest

from src.engines.contracts import (
    ConfirmationFamily,
    DataQualityStatus,
    EngineGateState,
    FamilyEvidence,
    LegSide,
    NumericRange,
    SetupAction,
)
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

NOW = datetime(2026, 1, 1, 12, tzinfo=UTC)


def _evidence(
    family: ConfirmationFamily = ConfirmationFamily.DERIVATIVES,
    *,
    age_seconds: float = 1,
    quality: float = 1,
) -> FamilyEvidence:
    return FamilyEvidence(
        family=family,
        score=0.8,
        confidence=0.9,
        quality=quality,
        max_source_timestamp_utc=NOW - timedelta(seconds=age_seconds),
        component_ids=(f"{family.value}_neutral_edge",),
        rationale="bounded neutral-family evidence",
    )


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


def _request() -> NeutralOpportunityRequest:
    return NeutralOpportunityRequest(
        mechanism=NeutralMechanism.CROSS_EXCHANGE_FUNDING,
        symbol="BTCUSDT",
        long_venue="bybit",
        short_venue="okx",
        decision_timestamp_utc=NOW,
        data_cutoff_utc=NOW,
        horizon="next-funding-window",
        evidence=(
            _evidence(),
            _evidence(ConfirmationFamily.CROSS_MARKET),
        ),
        regimes=(("liquidity", "LIQUID"), ("cross_market", "NEUTRAL")),
        expected_gross_edge_bps=NumericRange(40, 60, 80),
        costs=_costs(),
        capacity_notional=100_000,
        data_quality_status=DataQualityStatus.PASS,
        model_version="neutral-v1",
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
        gates=EngineGateState(
            kill_switch_active=False,
            operational_healthy=True,
            promotion_eligible=True,
            promotion_state="PAPER",
            risk_approved=True,
            risk_reason="approved",
        ),
    )


def test_approves_only_bounded_positive_two_leg_opportunity() -> None:
    decision = evaluate_neutral_opportunity(_request())

    assert decision.action == SetupAction.ARBITRAGE
    assert [leg.side for leg in decision.legs] == [LegSide.BUY, LegSide.SELL]
    assert decision.expected_cost_bps == NumericRange(7, 12, 20)
    assert decision.expected_value_after_cost_bps == NumericRange(20, 48, 73)
    assert decision.reason_codes == ("BOUNDED_CROSS_EXCHANGE_FUNDING_APPROVED",)


@pytest.mark.parametrize(
    ("opportunity", "reason"),
    [
        (
            replace(
                _request(),
                inventory=replace(_request().inventory, short_leg_available=False),
            ),
            "LEG_NOT_AVAILABLE",
        ),
        (
            replace(
                _request(),
                inventory=replace(
                    _request().inventory,
                    short_borrow_required=True,
                    short_borrow_confirmed=False,
                ),
            ),
            "SHORT_BORROW_NOT_CONFIRMED",
        ),
        (
            replace(
                _request(),
                inventory=replace(
                    _request().inventory,
                    transfer_required=True,
                    prefunded_inventory=False,
                ),
            ),
            "UNBOUNDED_TRANSFER_DEPENDENCY",
        ),
        (
            replace(
                _request(),
                inventory=replace(_request().inventory, short_venue_healthy=False),
            ),
            "VENUE_HEALTH_FAILED",
        ),
        (
            replace(_request(), maximum_unhedged_seconds=10),
            "UNHEDGED_WINDOW_TOO_LONG",
        ),
        (
            replace(
                _request(),
                stresses=replace(_request().stresses, one_leg_loss_bps=101),
            ),
            "STRESS_LOSS_EXCEEDS_LIMIT",
        ),
        (
            replace(
                _request(),
                stresses=replace(_request().stresses, margin_buffer_bps=100),
            ),
            "INSUFFICIENT_MARGIN_BUFFER",
        ),
        (
            replace(
                _request(),
                stresses=replace(_request().stresses, liquidation_distance_bps=100),
            ),
            "INSUFFICIENT_LIQUIDATION_DISTANCE",
        ),
    ],
)
def test_unbounded_leg_inventory_and_stress_risks_force_wait(
    opportunity: NeutralOpportunityRequest, reason: str
) -> None:
    decision = evaluate_neutral_opportunity(opportunity)

    assert decision.action == SetupAction.WAIT
    assert decision.reason_codes == (reason,)
    assert decision.legs == ()


def test_all_in_adverse_costs_must_leave_positive_lower_edge() -> None:
    request = replace(_request(), expected_gross_edge_bps=NumericRange(10, 20, 30))

    decision = evaluate_neutral_opportunity(request)

    assert decision.action == SetupAction.WAIT
    assert decision.expected_value_after_cost_bps.low == -10
    assert decision.reason_codes == ("INSUFFICIENT_CONSERVATIVE_EDGE_AFTER_ALL_COSTS",)


@pytest.mark.parametrize(
    ("opportunity", "reason"),
    [
        (
            replace(_request(), gates=replace(_request().gates, kill_switch_active=True)),
            "KILL_SWITCH_ACTIVE",
        ),
        (
            replace(_request(), gates=replace(_request().gates, promotion_eligible=False)),
            "PROMOTION_STATE_NOT_ELIGIBLE",
        ),
        (
            replace(
                _request(),
                gates=replace(
                    _request().gates,
                    risk_approved=False,
                    risk_reason="leg risk",
                ),
            ),
            "RISK_REJECTED:leg risk",
        ),
        (
            replace(_request(), data_quality_status=DataQualityStatus.DEGRADED),
            "DATA_QUALITY_NOT_PASS",
        ),
        (replace(_request(), capacity_notional=0), "NO_LIQUIDITY_CAPACITY"),
    ],
)
def test_safety_and_promotion_gates_force_wait(
    opportunity: NeutralOpportunityRequest, reason: str
) -> None:
    assert evaluate_neutral_opportunity(opportunity).reason_codes == (reason,)


def test_stale_or_low_quality_evidence_forces_wait() -> None:
    request = replace(
        _request(),
        evidence=(
            _evidence(age_seconds=60),
            _evidence(ConfirmationFamily.CROSS_MARKET),
        ),
    )
    assert evaluate_neutral_opportunity(request).reason_codes == ("STALE_OR_LOW_QUALITY_EVIDENCE",)


def test_required_independent_neutral_families_and_strength_are_enforced() -> None:
    missing = replace(_request(), evidence=(_evidence(),))
    assert evaluate_neutral_opportunity(missing).reason_codes == (
        "MISSING_REQUIRED_NEUTRAL_EVIDENCE",
    )

    weak_cross_market = replace(_evidence(ConfirmationFamily.CROSS_MARKET), score=0.1)
    weak = replace(_request(), evidence=(_evidence(), weak_cross_market))
    assert evaluate_neutral_opportunity(weak).reason_codes == (
        "INSUFFICIENT_NEUTRAL_EVIDENCE_STRENGTH",
    )


def test_future_duplicate_family_and_same_venue_requests_are_rejected() -> None:
    future = replace(_evidence(), max_source_timestamp_utc=NOW + timedelta(seconds=1))
    with pytest.raises(ValueError, match="cannot follow data cutoff"):
        evaluate_neutral_opportunity(
            replace(_request(), evidence=(future, *_request().evidence[1:]))
        )

    duplicate = (_evidence(), _evidence())
    with pytest.raises(ValueError, match="one evidence object per family"):
        evaluate_neutral_opportunity(replace(_request(), evidence=duplicate))

    with pytest.raises(ValueError, match="distinct venues"):
        evaluate_neutral_opportunity(replace(_request(), short_venue="bybit"))


def test_cost_and_stress_contracts_reject_invalid_values() -> None:
    with pytest.raises(ValueError, match="cannot be negative"):
        replace(_costs(), fees_bps=NumericRange(-1, 0, 1))
    with pytest.raises(ValueError, match="non-negative"):
        replace(_request().stresses, one_leg_loss_bps=-1)
    with pytest.raises(ValueError, match="Neutral Engine configuration"):
        NeutralEngineConfig(maximum_unhedged_seconds=0)
