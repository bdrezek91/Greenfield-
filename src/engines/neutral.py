"""Bounded funding/basis Neutral Engine with explicit leg-risk stresses."""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum

from src.engines.contracts import (
    ConfirmationFamily,
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


class NeutralMechanism(StrEnum):
    FUNDING_CAPTURE = "FUNDING_CAPTURE"
    SPOT_PERPETUAL_BASIS = "SPOT_PERPETUAL_BASIS"
    CROSS_EXCHANGE_FUNDING = "CROSS_EXCHANGE_FUNDING"
    CASH_AND_CARRY = "CASH_AND_CARRY"


class LegExecutionPolicy(StrEnum):
    ATOMIC_OR_CANCEL = "ATOMIC_OR_CANCEL"
    HEDGE_ON_PARTIAL = "HEDGE_ON_PARTIAL"


@dataclass(frozen=True, slots=True)
class NeutralCostBreakdown:
    fees_bps: NumericRange
    spread_bps: NumericRange
    slippage_bps: NumericRange
    funding_bps: NumericRange
    borrow_bps: NumericRange
    transfer_bps: NumericRange
    orphan_hedge_bps: NumericRange

    def __post_init__(self) -> None:
        if any(
            component.low < 0
            for component in (
                self.fees_bps,
                self.spread_bps,
                self.slippage_bps,
                self.funding_bps,
                self.borrow_bps,
                self.transfer_bps,
                self.orphan_hedge_bps,
            )
        ):
            raise ValueError("neutral cost components cannot be negative")

    def total(self) -> NumericRange:
        components = (
            self.fees_bps,
            self.spread_bps,
            self.slippage_bps,
            self.funding_bps,
            self.borrow_bps,
            self.transfer_bps,
            self.orphan_hedge_bps,
        )
        return NumericRange(
            low=sum(item.low for item in components),
            base=sum(item.base for item in components),
            high=sum(item.high for item in components),
        )


@dataclass(frozen=True, slots=True)
class NeutralInventoryState:
    long_leg_available: bool
    short_leg_available: bool
    short_borrow_required: bool
    short_borrow_confirmed: bool
    transfer_required: bool
    prefunded_inventory: bool
    long_venue_healthy: bool
    short_venue_healthy: bool


@dataclass(frozen=True, slots=True)
class NeutralStressBounds:
    one_leg_loss_bps: float
    venue_outage_loss_bps: float
    liquidation_stress_loss_bps: float
    margin_buffer_bps: float
    liquidation_distance_bps: float

    def __post_init__(self) -> None:
        values = (
            self.one_leg_loss_bps,
            self.venue_outage_loss_bps,
            self.liquidation_stress_loss_bps,
            self.margin_buffer_bps,
            self.liquidation_distance_bps,
        )
        if any(not math.isfinite(value) or value < 0 for value in values):
            raise ValueError("neutral stress bounds must be finite and non-negative")


@dataclass(frozen=True, slots=True)
class NeutralEngineConfig:
    maximum_data_age_seconds: float = 30.0
    minimum_evidence_quality: float = 0.7
    minimum_evidence_strength: float = 0.25
    minimum_net_edge_lower_bps: float = 0.0
    maximum_stress_loss_bps: float = 100.0
    minimum_margin_buffer_bps: float = 500.0
    minimum_liquidation_distance_bps: float = 1_000.0
    maximum_unhedged_seconds: float = 5.0

    def __post_init__(self) -> None:
        if (
            not math.isfinite(self.maximum_data_age_seconds)
            or self.maximum_data_age_seconds <= 0
            or not 0 <= self.minimum_evidence_quality <= 1
            or not 0 < self.minimum_evidence_strength <= 1
            or not math.isfinite(self.minimum_net_edge_lower_bps)
            or not math.isfinite(self.maximum_stress_loss_bps)
            or self.maximum_stress_loss_bps <= 0
            or not math.isfinite(self.minimum_margin_buffer_bps)
            or self.minimum_margin_buffer_bps <= 0
            or not math.isfinite(self.minimum_liquidation_distance_bps)
            or self.minimum_liquidation_distance_bps <= 0
            or not math.isfinite(self.maximum_unhedged_seconds)
            or self.maximum_unhedged_seconds <= 0
        ):
            raise ValueError("invalid Neutral Engine configuration")


@dataclass(frozen=True, slots=True)
class NeutralOpportunityRequest:
    mechanism: NeutralMechanism
    symbol: str
    long_venue: str
    short_venue: str
    decision_timestamp_utc: datetime
    data_cutoff_utc: datetime
    horizon: str
    evidence: tuple[FamilyEvidence, ...]
    regimes: tuple[tuple[str, str], ...]
    expected_gross_edge_bps: NumericRange
    costs: NeutralCostBreakdown
    capacity_notional: float
    data_quality_status: DataQualityStatus
    model_version: str
    feature_version: str
    inventory: NeutralInventoryState
    stresses: NeutralStressBounds
    execution_policy: LegExecutionPolicy
    maximum_unhedged_seconds: float
    entry_condition: str
    invalidation: str
    hedge_logic: str
    gates: EngineGateState


def evaluate_neutral_opportunity(
    request: NeutralOpportunityRequest,
    config: NeutralEngineConfig | None = None,
) -> SetupDecision:
    """Return ARBITRAGE only for positive, bounded, executable two-leg edge."""
    config = config or NeutralEngineConfig()
    _validate_request(request)
    costs = request.costs.total()
    net = NumericRange(
        low=request.expected_gross_edge_bps.low - costs.high,
        base=request.expected_gross_edge_bps.base - costs.base,
        high=request.expected_gross_edge_bps.high - costs.low,
    )
    reason = _rejection_reason(request, net=net, config=config)
    if reason is not None:
        return _wait(request, costs=costs, net=net, reason=reason)
    return SetupDecision(
        action=SetupAction.ARBITRAGE,
        targets=(MarketTarget(request.symbol, (request.long_venue, request.short_venue)),),
        legs=(
            SetupLeg(request.symbol, request.long_venue, LegSide.BUY),
            SetupLeg(request.symbol, request.short_venue, LegSide.SELL),
        ),
        decision_timestamp_utc=request.decision_timestamp_utc,
        data_cutoff_utc=request.data_cutoff_utc,
        horizon=request.horizon,
        evidence=request.evidence,
        regimes=request.regimes,
        entry_condition=request.entry_condition,
        invalidation=request.invalidation,
        stop_or_hedge_logic=request.hedge_logic,
        expected_cost_bps=costs,
        expected_value_after_cost_bps=net,
        capacity_notional=request.capacity_notional,
        data_quality_status=request.data_quality_status,
        model_version=request.model_version,
        feature_version=request.feature_version,
        reason_codes=(f"BOUNDED_{request.mechanism.value}_APPROVED",),
    )


def _validate_request(request: NeutralOpportunityRequest) -> None:
    decision = _utc(request.decision_timestamp_utc, "neutral decision timestamp")
    cutoff = _utc(request.data_cutoff_utc, "neutral data cutoff")
    if cutoff > decision:
        raise ValueError("neutral data cutoff cannot follow decision time")
    if (
        not request.symbol.strip()
        or not request.long_venue.strip()
        or not request.short_venue.strip()
        or request.long_venue.lower() == request.short_venue.lower()
    ):
        raise ValueError("neutral opportunity requires a symbol and distinct venues")
    families = [item.family for item in request.evidence]
    if len(set(families)) != len(families):
        raise ValueError("neutral request permits one evidence object per family")
    if any(
        _utc(item.max_source_timestamp_utc, "neutral source timestamp") > cutoff
        for item in request.evidence
    ):
        raise ValueError("neutral evidence cannot follow data cutoff")
    if not math.isfinite(request.capacity_notional) or request.capacity_notional < 0:
        raise ValueError("neutral capacity must be finite and non-negative")
    if not math.isfinite(request.maximum_unhedged_seconds) or request.maximum_unhedged_seconds < 0:
        raise ValueError("neutral unhedged time must be finite and non-negative")


def _rejection_reason(
    request: NeutralOpportunityRequest,
    *,
    net: NumericRange,
    config: NeutralEngineConfig,
) -> str | None:
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
    families = {item.family for item in request.evidence}
    required_families = {
        ConfirmationFamily.DERIVATIVES,
        ConfirmationFamily.CROSS_MARKET,
    }
    if not required_families.issubset(families):
        return "MISSING_REQUIRED_NEUTRAL_EVIDENCE"
    decision = request.decision_timestamp_utc.astimezone(UTC)
    if any(
        item.quality < config.minimum_evidence_quality
        or (decision - item.max_source_timestamp_utc.astimezone(UTC)).total_seconds()
        > config.maximum_data_age_seconds
        for item in request.evidence
    ):
        return "STALE_OR_LOW_QUALITY_EVIDENCE"
    if any(item.effective_score < config.minimum_evidence_strength for item in request.evidence):
        return "INSUFFICIENT_NEUTRAL_EVIDENCE_STRENGTH"
    inventory = request.inventory
    if not inventory.long_venue_healthy or not inventory.short_venue_healthy:
        return "VENUE_HEALTH_FAILED"
    if not inventory.long_leg_available or not inventory.short_leg_available:
        return "LEG_NOT_AVAILABLE"
    if inventory.short_borrow_required and not inventory.short_borrow_confirmed:
        return "SHORT_BORROW_NOT_CONFIRMED"
    if inventory.transfer_required and not inventory.prefunded_inventory:
        return "UNBOUNDED_TRANSFER_DEPENDENCY"
    if (
        request.execution_policy == LegExecutionPolicy.HEDGE_ON_PARTIAL
        and request.maximum_unhedged_seconds > config.maximum_unhedged_seconds
    ):
        return "UNHEDGED_WINDOW_TOO_LONG"
    stress = request.stresses
    if (
        max(
            stress.one_leg_loss_bps,
            stress.venue_outage_loss_bps,
            stress.liquidation_stress_loss_bps,
        )
        > config.maximum_stress_loss_bps
    ):
        return "STRESS_LOSS_EXCEEDS_LIMIT"
    if stress.margin_buffer_bps < config.minimum_margin_buffer_bps:
        return "INSUFFICIENT_MARGIN_BUFFER"
    if stress.liquidation_distance_bps < config.minimum_liquidation_distance_bps:
        return "INSUFFICIENT_LIQUIDATION_DISTANCE"
    if net.low <= config.minimum_net_edge_lower_bps:
        return "INSUFFICIENT_CONSERVATIVE_EDGE_AFTER_ALL_COSTS"
    return None


def _wait(
    request: NeutralOpportunityRequest,
    *,
    costs: NumericRange,
    net: NumericRange,
    reason: str,
) -> SetupDecision:
    return SetupDecision(
        action=SetupAction.WAIT,
        targets=(MarketTarget(request.symbol, (request.long_venue, request.short_venue)),),
        legs=(),
        decision_timestamp_utc=request.decision_timestamp_utc,
        data_cutoff_utc=request.data_cutoff_utc,
        horizon=request.horizon,
        evidence=request.evidence,
        regimes=request.regimes,
        entry_condition=request.entry_condition,
        invalidation=request.invalidation,
        stop_or_hedge_logic=request.hedge_logic,
        expected_cost_bps=costs,
        expected_value_after_cost_bps=net,
        capacity_notional=request.capacity_notional,
        data_quality_status=request.data_quality_status,
        model_version=request.model_version,
        feature_version=request.feature_version,
        reason_codes=(reason,),
    )


def _utc(value: datetime, name: str) -> datetime:
    if value.tzinfo is None:
        raise ValueError(f"{name} must be timezone-aware")
    return value.astimezone(UTC)
