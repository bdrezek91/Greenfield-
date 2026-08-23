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
    MarketTarget,
    NumericRange,
    SetupAction,
    SetupLeg,
)
from src.engines.directional import (
    DirectionalEngineConfig,
    DirectionalSetupRequest,
    evaluate_directional_setup,
)

NOW = datetime(2026, 1, 1, 12, tzinfo=UTC)


def _evidence(
    family: ConfirmationFamily,
    score: float,
    *,
    components: tuple[str, ...] | None = None,
    age_seconds: float = 1,
    quality: float = 1,
) -> FamilyEvidence:
    return FamilyEvidence(
        family=family,
        score=score,
        confidence=1,
        quality=quality,
        max_source_timestamp_utc=NOW - timedelta(seconds=age_seconds),
        component_ids=components or (f"{family.value}_score",),
        rationale="independently aggregated family evidence",
    )


def _request(evidence: tuple[FamilyEvidence, ...]) -> DirectionalSetupRequest:
    return DirectionalSetupRequest(
        target=MarketTarget("BTCUSDT", ("bybit",)),
        decision_timestamp_utc=NOW,
        data_cutoff_utc=NOW,
        horizon="15m-4h",
        evidence=evidence,
        regimes=(("trend", "UPTREND"), ("liquidity", "LIQUID")),
        entry_condition="limit inside validated entry zone",
        invalidation="auction structure invalidated",
        stop_logic="hard stop below invalidation",
        expected_gross_value_bps=NumericRange(20, 35, 55),
        expected_cost_bps=NumericRange(2, 4, 8),
        capacity_notional=100_000,
        data_quality_status=DataQualityStatus.PASS,
        model_version="directional-v1",
        feature_version="gold-v1",
        gates=EngineGateState(
            kill_switch_active=False,
            operational_healthy=True,
            promotion_eligible=True,
            promotion_state="SHADOW",
            risk_approved=True,
            risk_reason="approved",
        ),
    )


def _long_evidence() -> tuple[FamilyEvidence, ...]:
    return (
        _evidence(ConfirmationFamily.PRICE_AUCTION, 0.8),
        _evidence(ConfirmationFamily.ORDER_FLOW, 0.7),
        _evidence(ConfirmationFamily.DERIVATIVES, 0.6),
    )


def test_three_independent_families_can_approve_long() -> None:
    decision = evaluate_directional_setup(_request(_long_evidence()))

    assert decision.action == SetupAction.LONG
    assert decision.legs == (SetupLeg("BTCUSDT", "bybit", LegSide.BUY),)
    assert decision.expected_value_after_cost_bps == NumericRange(12, 31, 53)
    assert len(decision.evidence) == 3
    assert decision.reason_codes == ("DIRECTIONAL_EDGE_APPROVED",)


def test_three_independent_negative_families_can_approve_short() -> None:
    evidence = tuple(replace(item, score=-item.score) for item in _long_evidence())

    decision = evaluate_directional_setup(_request(evidence))

    assert decision.action == SetupAction.SHORT
    assert decision.legs[0].side == LegSide.SELL


def test_many_correlated_components_inside_one_family_still_count_once() -> None:
    price = _evidence(
        ConfirmationFamily.PRICE_AUCTION,
        0.9,
        components=("rsi", "macd", "stochastic", "ma_distance", "momentum"),
    )

    decision = evaluate_directional_setup(_request((price,)))

    assert decision.action == SetupAction.WAIT
    assert decision.reason_codes == ("INSUFFICIENT_INDEPENDENT_CONFIRMATIONS",)


def test_duplicate_family_objects_are_rejected_instead_of_double_counted() -> None:
    first = _evidence(ConfirmationFamily.ORDER_FLOW, 0.8)
    second = replace(first, component_ids=("cvd",))

    with pytest.raises(ValueError, match="one evidence object per family"):
        evaluate_directional_setup(_request((first, second)))


def test_conflicting_high_quality_families_force_wait() -> None:
    evidence = (*_long_evidence(), _evidence(ConfirmationFamily.CROSS_MARKET, -0.9))

    decision = evaluate_directional_setup(_request(evidence))

    assert decision.action == SetupAction.WAIT
    assert decision.reason_codes == ("CONFLICTING_INDEPENDENT_FAMILIES",)


@pytest.mark.parametrize(
    ("mutator", "reason"),
    [
        (
            lambda request: replace(
                request,
                gates=replace(request.gates, kill_switch_active=True),
            ),
            "KILL_SWITCH_ACTIVE",
        ),
        (
            lambda request: replace(
                request,
                gates=replace(request.gates, operational_healthy=False),
            ),
            "OPERATIONAL_HEALTH_FAILED",
        ),
        (
            lambda request: replace(request, data_quality_status=DataQualityStatus.DEGRADED),
            "DATA_QUALITY_NOT_PASS",
        ),
        (
            lambda request: replace(
                request,
                gates=replace(request.gates, promotion_eligible=False),
            ),
            "PROMOTION_STATE_NOT_ELIGIBLE",
        ),
        (
            lambda request: replace(
                request,
                gates=replace(
                    request.gates,
                    risk_approved=False,
                    risk_reason="drawdown guard",
                ),
            ),
            "RISK_REJECTED:drawdown guard",
        ),
        (lambda request: replace(request, capacity_notional=0), "NO_LIQUIDITY_CAPACITY"),
    ],
)
def test_non_overridable_gates_force_wait(mutator, reason: str) -> None:
    decision = evaluate_directional_setup(mutator(_request(_long_evidence())))

    assert decision.action == SetupAction.WAIT
    assert decision.reason_codes == (reason,)
    assert decision.legs == ()


def test_stale_or_low_quality_evidence_and_costs_force_wait() -> None:
    stale = replace(
        _request(_long_evidence()),
        evidence=(
            _evidence(ConfirmationFamily.PRICE_AUCTION, 0.8, age_seconds=60),
            *_long_evidence()[1:],
        ),
    )
    assert evaluate_directional_setup(stale).reason_codes == ("STALE_OR_LOW_QUALITY_EVIDENCE",)

    costly = replace(
        _request(_long_evidence()),
        expected_gross_value_bps=NumericRange(5, 10, 15),
        expected_cost_bps=NumericRange(5, 8, 12),
    )
    assert evaluate_directional_setup(costly).reason_codes == (
        "INSUFFICIENT_CONSERVATIVE_EDGE_AFTER_COSTS",
    )

    old_cutoff = replace(
        _request(_long_evidence()),
        decision_timestamp_utc=NOW + timedelta(minutes=5),
    )
    assert evaluate_directional_setup(old_cutoff).reason_codes == ("STALE_OR_LOW_QUALITY_EVIDENCE",)


def test_setup_contract_requires_wait_reason_and_valid_arbitrage_legs() -> None:
    request = _request(_long_evidence())
    wait = evaluate_directional_setup(
        request,
        DirectionalEngineConfig(minimum_confirming_families=6),
    )
    with pytest.raises(ValueError, match="WAIT requires"):
        replace(wait, reason_codes=())

    arbitrage = replace(
        wait,
        action=SetupAction.ARBITRAGE,
        targets=(MarketTarget("BTCUSDT", ("bybit", "okx")),),
        legs=(
            SetupLeg("BTCUSDT", "bybit", LegSide.BUY),
            SetupLeg("BTCUSDT", "okx", LegSide.SELL),
        ),
        entry_condition="atomic bounded-leg entry",
        invalidation="basis no longer covers costs",
        stop_or_hedge_logic="cancel or immediately hedge orphan leg",
        reason_codes=("NEUTRAL_EDGE_APPROVED",),
    )
    assert arbitrage.action == SetupAction.ARBITRAGE
    with pytest.raises(ValueError, match="opposing"):
        replace(arbitrage, legs=arbitrage.legs[:1])


def test_future_evidence_and_naive_decision_time_are_rejected() -> None:
    future = replace(
        _long_evidence()[0],
        max_source_timestamp_utc=NOW + timedelta(seconds=1),
    )
    with pytest.raises(ValueError, match="cannot follow data cutoff"):
        evaluate_directional_setup(_request((future, *_long_evidence()[1:])))

    with pytest.raises(ValueError, match="timezone-aware"):
        evaluate_directional_setup(
            replace(_request(_long_evidence()), decision_timestamp_utc=NOW.replace(tzinfo=None))
        )
