"""Directional LONG/SHORT/WAIT engine over independent family evidence."""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import UTC, datetime

from src.engines.contracts import (
    DataQualityStatus,
    EngineGateState,
    FamilyEvidence,
    LegSide,
    MarketTarget,
    NumericRange,
    SetupAction,
    SetupDecision,
    SetupLeg,
)


@dataclass(frozen=True, slots=True)
class DirectionalEngineConfig:
    minimum_confirming_families: int = 3
    family_vote_threshold: float = 0.25
    minimum_evidence_quality: float = 0.7
    maximum_data_age_seconds: float = 30.0
    minimum_net_ev_lower_bps: float = 0.0

    def __post_init__(self) -> None:
        if self.minimum_confirming_families < 1:
            raise ValueError("directional engine requires confirming families")
        if (
            not 0 < self.family_vote_threshold <= 1
            or not 0 <= self.minimum_evidence_quality <= 1
            or not math.isfinite(self.maximum_data_age_seconds)
            or self.maximum_data_age_seconds <= 0
            or not math.isfinite(self.minimum_net_ev_lower_bps)
        ):
            raise ValueError("invalid directional engine thresholds")


@dataclass(frozen=True, slots=True)
class DirectionalSetupRequest:
    target: MarketTarget
    decision_timestamp_utc: datetime
    data_cutoff_utc: datetime
    horizon: str
    evidence: tuple[FamilyEvidence, ...]
    regimes: tuple[tuple[str, str], ...]
    entry_condition: str
    invalidation: str
    stop_logic: str
    expected_gross_value_bps: NumericRange
    expected_cost_bps: NumericRange
    capacity_notional: float
    data_quality_status: DataQualityStatus
    model_version: str
    feature_version: str
    gates: EngineGateState


def evaluate_directional_setup(
    request: DirectionalSetupRequest,
    config: DirectionalEngineConfig | None = None,
) -> SetupDecision:
    """Return LONG/SHORT only when independent evidence, cost, and gates pass."""
    config = config or DirectionalEngineConfig()
    _validate_request(request)
    net_value = NumericRange(
        low=request.expected_gross_value_bps.low - request.expected_cost_bps.high,
        base=request.expected_gross_value_bps.base - request.expected_cost_bps.base,
        high=request.expected_gross_value_bps.high - request.expected_cost_bps.low,
    )
    gate_reason = _gate_reason(request)
    if gate_reason is not None:
        return _wait(request, net_value, gate_reason)
    decision = request.decision_timestamp_utc.astimezone(UTC)
    eligible = tuple(
        item
        for item in request.evidence
        if item.quality >= config.minimum_evidence_quality
        and (decision - item.max_source_timestamp_utc.astimezone(UTC)).total_seconds()
        <= config.maximum_data_age_seconds
    )
    if len(eligible) != len(request.evidence):
        return _wait(request, net_value, "STALE_OR_LOW_QUALITY_EVIDENCE")

    long_votes = sum(item.effective_score >= config.family_vote_threshold for item in eligible)
    short_votes = sum(item.effective_score <= -config.family_vote_threshold for item in eligible)
    if long_votes and short_votes:
        return _wait(request, net_value, "CONFLICTING_INDEPENDENT_FAMILIES")
    if net_value.low <= config.minimum_net_ev_lower_bps:
        return _wait(request, net_value, "INSUFFICIENT_CONSERVATIVE_EDGE_AFTER_COSTS")
    if long_votes >= config.minimum_confirming_families:
        return _actionable(request, net_value, SetupAction.LONG)
    if short_votes >= config.minimum_confirming_families:
        return _actionable(request, net_value, SetupAction.SHORT)
    return _wait(request, net_value, "INSUFFICIENT_INDEPENDENT_CONFIRMATIONS")


def _validate_request(request: DirectionalSetupRequest) -> None:
    decision = _utc(request.decision_timestamp_utc, "decision timestamp")
    cutoff = _utc(request.data_cutoff_utc, "data cutoff")
    if cutoff > decision:
        raise ValueError("directional data cutoff cannot follow decision time")
    families = [item.family for item in request.evidence]
    if len(set(families)) != len(families):
        raise ValueError("directional request permits one evidence object per family")
    if any(
        _utc(item.max_source_timestamp_utc, "source timestamp") > cutoff
        for item in request.evidence
    ):
        raise ValueError("directional evidence cannot follow data cutoff")
    if request.capacity_notional < 0 or not math.isfinite(request.capacity_notional):
        raise ValueError("directional capacity must be finite and non-negative")
    if request.expected_cost_bps.low < 0:
        raise ValueError("directional expected costs cannot be negative")


def _gate_reason(request: DirectionalSetupRequest) -> str | None:
    if request.gates.kill_switch_active:
        return "KILL_SWITCH_ACTIVE"
    if not request.gates.operational_healthy:
        return "OPERATIONAL_HEALTH_FAILED"
    if request.data_quality_status != DataQualityStatus.PASS:
        return "DATA_QUALITY_NOT_PASS"
    if not request.gates.promotion_eligible:
        return "PROMOTION_STATE_NOT_ELIGIBLE"
    if not request.gates.risk_approved:
        return f"RISK_REJECTED:{request.gates.risk_reason}"
    if request.capacity_notional <= 0:
        return "NO_LIQUIDITY_CAPACITY"
    return None


def _wait(request: DirectionalSetupRequest, net_value: NumericRange, reason: str) -> SetupDecision:
    return SetupDecision(
        action=SetupAction.WAIT,
        targets=(request.target,),
        legs=(),
        decision_timestamp_utc=request.decision_timestamp_utc,
        data_cutoff_utc=request.data_cutoff_utc,
        horizon=request.horizon,
        evidence=request.evidence,
        regimes=request.regimes,
        entry_condition=request.entry_condition,
        invalidation=request.invalidation,
        stop_or_hedge_logic=request.stop_logic,
        expected_cost_bps=request.expected_cost_bps,
        expected_value_after_cost_bps=net_value,
        capacity_notional=request.capacity_notional,
        data_quality_status=request.data_quality_status,
        model_version=request.model_version,
        feature_version=request.feature_version,
        reason_codes=(reason,),
    )


def _actionable(
    request: DirectionalSetupRequest,
    net_value: NumericRange,
    action: SetupAction,
) -> SetupDecision:
    side = LegSide.BUY if action == SetupAction.LONG else LegSide.SELL
    return SetupDecision(
        action=action,
        targets=(request.target,),
        legs=(
            SetupLeg(
                symbol=request.target.symbol,
                venue=request.target.venues[0],
                side=side,
            ),
        ),
        decision_timestamp_utc=request.decision_timestamp_utc,
        data_cutoff_utc=request.data_cutoff_utc,
        horizon=request.horizon,
        evidence=request.evidence,
        regimes=request.regimes,
        entry_condition=request.entry_condition,
        invalidation=request.invalidation,
        stop_or_hedge_logic=request.stop_logic,
        expected_cost_bps=request.expected_cost_bps,
        expected_value_after_cost_bps=net_value,
        capacity_notional=request.capacity_notional,
        data_quality_status=request.data_quality_status,
        model_version=request.model_version,
        feature_version=request.feature_version,
        reason_codes=("DIRECTIONAL_EDGE_APPROVED",),
    )


def _utc(value: datetime, name: str) -> datetime:
    if value.tzinfo is None:
        raise ValueError(f"{name} must be timezone-aware")
    return value.astimezone(UTC)
