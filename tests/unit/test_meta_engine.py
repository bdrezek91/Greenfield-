from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest

from src.engines.contracts import (
    ConfirmationFamily,
    DataQualityStatus,
    FamilyEvidence,
    LegSide,
    MarketTarget,
    NumericRange,
    SetupAction,
    SetupDecision,
    SetupLeg,
)
from src.engines.meta import (
    CorrelationPair,
    EngineCandidate,
    EngineKind,
    MetaEngineConfig,
    MetaPortfolioState,
    evaluate_meta_candidates,
)

NOW = datetime(2026, 1, 1, 12, tzinfo=UTC)


def _evidence() -> tuple[FamilyEvidence, ...]:
    return (
        FamilyEvidence(
            family=ConfirmationFamily.ORDER_FLOW,
            score=0.8,
            confidence=0.9,
            quality=1,
            max_source_timestamp_utc=NOW - timedelta(seconds=2),
            component_ids=("cvd_absorption",),
            rationale="family score",
        ),
    )


def _setup(
    action: SetupAction = SetupAction.LONG,
    *,
    symbol: str = "BTCUSDT",
    venue: str = "bybit",
    value: NumericRange | None = None,
    capacity: float = 200_000,
) -> SetupDecision:
    value = value or NumericRange(10, 20, 30)
    if action == SetupAction.WAIT:
        legs: tuple[SetupLeg, ...] = ()
        reasons = ("NO_EDGE",)
    else:
        side = LegSide.BUY if action == SetupAction.LONG else LegSide.SELL
        legs = (SetupLeg(symbol, venue, side),)
        reasons = ("ENGINE_APPROVED",)
    return SetupDecision(
        action=action,
        targets=(MarketTarget(symbol, (venue,)),),
        legs=legs,
        decision_timestamp_utc=NOW,
        data_cutoff_utc=NOW - timedelta(seconds=1),
        horizon="15m-4h",
        evidence=_evidence(),
        regimes=(("trend", "UPTREND"),),
        entry_condition="validated entry",
        invalidation="structure invalidation",
        stop_or_hedge_logic="bounded stop",
        expected_cost_bps=NumericRange(2, 3, 5),
        expected_value_after_cost_bps=value,
        capacity_notional=capacity,
        data_quality_status=DataQualityStatus.PASS,
        model_version="model-v1",
        feature_version="feature-v1",
        reason_codes=reasons,
    )


def _arbitrage(value: NumericRange | None = None) -> SetupDecision:
    value = value or NumericRange(15, 25, 35)
    base = _setup(SetupAction.WAIT)
    return replace(
        base,
        action=SetupAction.ARBITRAGE,
        targets=(MarketTarget("BTCUSDT", ("bybit", "okx")),),
        legs=(
            SetupLeg("BTCUSDT", "bybit", LegSide.BUY),
            SetupLeg("BTCUSDT", "okx", LegSide.SELL),
        ),
        entry_condition="bounded simultaneous leg entry",
        invalidation="basis below all-in costs",
        stop_or_hedge_logic="cancel or hedge orphan leg",
        expected_value_after_cost_bps=value,
        reason_codes=("NEUTRAL_APPROVED",),
    )


def _candidate(
    engine_id: str,
    setup: SetupDecision,
    kind: EngineKind = EngineKind.DIRECTIONAL,
    *,
    approved: bool = True,
) -> EngineCandidate:
    return EngineCandidate(engine_id, kind, setup, approved)


def _portfolio(**changes: object) -> MetaPortfolioState:
    base = MetaPortfolioState(
        gross_exposure_notional=100_000,
        exposure_by_symbol=(("ETHUSDT", 100_000),),
        correlations=(CorrelationPair("BTCUSDT", "ETHUSDT", 0.8),),
        available_risk_notional=150_000,
        kill_switch_active=False,
        operational_healthy=True,
        portfolio_risk_approved=True,
        risk_reason="approved",
    )
    return replace(base, **changes)


def test_selects_best_edge_after_uncertainty_penalty() -> None:
    stable = _candidate("stable", _setup(value=NumericRange(12, 22, 28)))
    uncertain = _candidate("uncertain", _setup(value=NumericRange(1, 30, 70)))

    decision = evaluate_meta_candidates(
        (uncertain, stable), decision_timestamp_utc=NOW, portfolio=_portfolio()
    )

    assert decision.action == SetupAction.LONG
    assert decision.selected_engine_id == "stable"
    assert decision.allocated_notional == 150_000
    assert decision.reason_codes == ("BEST_ELIGIBLE_EDGE_AFTER_COST_AND_UNCERTAINTY",)


def test_neutral_setup_wins_when_its_after_cost_edge_is_stronger() -> None:
    directional = _candidate("directional", _setup())
    neutral = _candidate("neutral", _arbitrage(), EngineKind.NEUTRAL)

    decision = evaluate_meta_candidates(
        (directional, neutral), decision_timestamp_utc=NOW, portfolio=_portfolio()
    )

    assert decision.action == SetupAction.ARBITRAGE
    assert decision.selected_engine_id == "neutral"


def test_opposing_directional_setups_for_same_symbol_force_wait() -> None:
    long = _candidate("long", _setup(SetupAction.LONG))
    short = _candidate("short", _setup(SetupAction.SHORT))

    decision = evaluate_meta_candidates(
        (long, short), decision_timestamp_utc=NOW, portfolio=_portfolio()
    )

    assert decision.action == SetupAction.WAIT
    assert decision.reason_codes == ("CONFLICTING_DIRECTIONAL_SETUPS",)


@pytest.mark.parametrize(
    ("portfolio", "reason"),
    [
        (_portfolio(kill_switch_active=True), "GLOBAL_KILL_SWITCH_ACTIVE"),
        (
            _portfolio(operational_healthy=False),
            "GLOBAL_OPERATIONAL_HEALTH_FAILED",
        ),
        (
            _portfolio(portfolio_risk_approved=False, risk_reason="drawdown"),
            "GLOBAL_RISK_REJECTED:drawdown",
        ),
        (
            _portfolio(available_risk_notional=0),
            "NO_AVAILABLE_PORTFOLIO_RISK",
        ),
    ],
)
def test_global_gates_cannot_be_overridden(portfolio: MetaPortfolioState, reason: str) -> None:
    decision = evaluate_meta_candidates(
        (_candidate("strong", _setup(value=NumericRange(100, 200, 300))),),
        decision_timestamp_utc=NOW,
        portfolio=portfolio,
    )

    assert decision.action == SetupAction.WAIT
    assert decision.reason_codes == (reason,)
    assert decision.rankings[0].reason == reason


def test_allocation_is_bounded_by_gross_symbol_and_correlated_exposure() -> None:
    candidate = _candidate("btc", _setup(capacity=1_000_000))
    config = MetaEngineConfig(
        maximum_gross_exposure_notional=500_000,
        maximum_symbol_exposure_notional=250_000,
        maximum_correlated_exposure_notional=180_000,
    )

    decision = evaluate_meta_candidates(
        (candidate,),
        decision_timestamp_utc=NOW,
        portfolio=_portfolio(available_risk_notional=400_000),
        config=config,
    )

    assert decision.allocated_notional == 80_000


def test_missing_correlation_evidence_fails_closed() -> None:
    decision = evaluate_meta_candidates(
        (_candidate("btc", _setup()),),
        decision_timestamp_utc=NOW,
        portfolio=_portfolio(correlations=()),
    )

    assert decision.action == SetupAction.WAIT
    assert decision.rankings[0].reason == "MISSING_CORRELATION_EVIDENCE"


def test_wait_unapproved_stale_future_and_bad_quality_setups_are_ineligible() -> None:
    wait = _candidate("wait", _setup(SetupAction.WAIT))
    unapproved = _candidate("unapproved", _setup(), approved=False)
    stale = _candidate(
        "stale",
        replace(
            _setup(),
            decision_timestamp_utc=NOW - timedelta(minutes=2),
            data_cutoff_utc=NOW - timedelta(minutes=2),
            evidence=tuple(
                replace(
                    item,
                    max_source_timestamp_utc=NOW - timedelta(minutes=2, seconds=1),
                )
                for item in _evidence()
            ),
        ),
    )
    future = _candidate(
        "future",
        replace(
            _setup(),
            decision_timestamp_utc=NOW + timedelta(seconds=1),
        ),
    )
    degraded = _candidate(
        "degraded",
        replace(_setup(), data_quality_status=DataQualityStatus.DEGRADED),
    )

    decision = evaluate_meta_candidates(
        (wait, unapproved, stale, future, degraded),
        decision_timestamp_utc=NOW,
        portfolio=_portfolio(),
    )

    assert decision.action == SetupAction.WAIT
    assert decision.reason_codes == ("NO_ELIGIBLE_ENGINE_SETUP",)
    assert {ranking.reason for ranking in decision.rankings} == {
        "ENGINE_RETURNED_WAIT",
        "RESEARCH_PROMOTION_NOT_APPROVED",
        "STALE_SETUP",
        "SETUP_FROM_FUTURE",
        "SETUP_DATA_QUALITY_NOT_PASS",
    }


def test_non_positive_conservative_or_risk_adjusted_edge_is_rejected() -> None:
    no_lower_edge = _candidate("no-lower", _setup(value=NumericRange(0, 20, 30)))
    uncertainty_dominates = _candidate("uncertain", _setup(value=NumericRange(1, 2, 20)))

    decision = evaluate_meta_candidates(
        (no_lower_edge, uncertainty_dominates),
        decision_timestamp_utc=NOW,
        portfolio=_portfolio(),
    )

    assert decision.action == SetupAction.WAIT
    assert all(ranking.reason == "NON_POSITIVE_RISK_ADJUSTED_EDGE" for ranking in decision.rankings)


def test_deterministic_tie_break_uses_engine_id() -> None:
    second = _candidate("z-engine", _setup())
    first = _candidate("a-engine", _setup())

    decision = evaluate_meta_candidates(
        (second, first), decision_timestamp_utc=NOW, portfolio=_portfolio()
    )

    assert decision.selected_engine_id == "a-engine"


def test_rejects_duplicate_candidate_ids_and_naive_meta_timestamp() -> None:
    candidate = _candidate("same", _setup())
    with pytest.raises(ValueError, match="ids must be unique"):
        evaluate_meta_candidates(
            (candidate, candidate), decision_timestamp_utc=NOW, portfolio=_portfolio()
        )
    with pytest.raises(ValueError, match="timezone-aware"):
        evaluate_meta_candidates(
            (candidate,),
            decision_timestamp_utc=NOW.replace(tzinfo=None),
            portfolio=_portfolio(),
        )
