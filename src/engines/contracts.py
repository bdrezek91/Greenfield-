"""Auditable setup contracts shared by decision engines."""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum


class SetupAction(StrEnum):
    LONG = "LONG"
    SHORT = "SHORT"
    WAIT = "WAIT"
    ARBITRAGE = "ARBITRAGE"


class LegSide(StrEnum):
    BUY = "BUY"
    SELL = "SELL"


class DataQualityStatus(StrEnum):
    PASS = "PASS"
    DEGRADED = "DEGRADED"
    FAIL = "FAIL"


class ConfirmationFamily(StrEnum):
    PRICE_AUCTION = "price_auction"
    ORDER_FLOW = "order_flow"
    DERIVATIVES = "derivatives"
    VOLATILITY_OPTIONS = "volatility_options"
    CROSS_MARKET = "cross_market"
    REGIME_ANALOG = "regime_analog"


@dataclass(frozen=True, slots=True)
class NumericRange:
    low: float
    base: float
    high: float

    def __post_init__(self) -> None:
        if not all(math.isfinite(value) for value in (self.low, self.base, self.high)):
            raise ValueError("numeric range must be finite")
        if not self.low <= self.base <= self.high:
            raise ValueError("numeric range must be ordered low <= base <= high")


@dataclass(frozen=True, slots=True)
class MarketTarget:
    symbol: str
    venues: tuple[str, ...]

    def __post_init__(self) -> None:
        if not self.symbol or self.symbol != self.symbol.strip():
            raise ValueError("market target symbol must be non-empty and trimmed")
        if not self.venues or any(not venue or venue != venue.strip() for venue in self.venues):
            raise ValueError("market target requires trimmed venues")
        if len(set(venue.lower() for venue in self.venues)) != len(self.venues):
            raise ValueError("market target venues must be unique")


@dataclass(frozen=True, slots=True)
class SetupLeg:
    symbol: str
    venue: str
    side: LegSide

    def __post_init__(self) -> None:
        if (
            not self.symbol
            or self.symbol != self.symbol.strip()
            or not self.venue
            or self.venue != self.venue.strip()
        ):
            raise ValueError("setup leg symbol and venue must be non-empty and trimmed")


@dataclass(frozen=True, slots=True)
class FamilyEvidence:
    family: ConfirmationFamily
    score: float
    confidence: float
    quality: float
    max_source_timestamp_utc: datetime
    component_ids: tuple[str, ...]
    rationale: str

    def __post_init__(self) -> None:
        if not math.isfinite(self.score) or not -1 <= self.score <= 1:
            raise ValueError("family evidence score must be between -1 and 1")
        if (
            not math.isfinite(self.confidence)
            or not 0 <= self.confidence <= 1
            or not math.isfinite(self.quality)
            or not 0 <= self.quality <= 1
        ):
            raise ValueError("family confidence and quality must be between zero and one")
        _utc(self.max_source_timestamp_utc, "family source timestamp")
        if not self.component_ids or any(not item.strip() for item in self.component_ids):
            raise ValueError("family evidence requires named components")
        if len(set(self.component_ids)) != len(self.component_ids):
            raise ValueError("family evidence components must be unique")
        if not self.rationale.strip():
            raise ValueError("family evidence requires rationale")

    @property
    def effective_score(self) -> float:
        return self.score * self.confidence * self.quality


@dataclass(frozen=True, slots=True)
class EngineGateState:
    kill_switch_active: bool
    operational_healthy: bool
    promotion_eligible: bool
    promotion_state: str
    risk_approved: bool
    risk_reason: str

    def __post_init__(self) -> None:
        if not self.promotion_state.strip() or not self.risk_reason.strip():
            raise ValueError("engine gate state requires promotion and risk reasons")


@dataclass(frozen=True, slots=True)
class SetupDecision:
    action: SetupAction
    targets: tuple[MarketTarget, ...]
    legs: tuple[SetupLeg, ...]
    decision_timestamp_utc: datetime
    data_cutoff_utc: datetime
    horizon: str
    evidence: tuple[FamilyEvidence, ...]
    regimes: tuple[tuple[str, str], ...]
    entry_condition: str
    invalidation: str
    stop_or_hedge_logic: str
    expected_cost_bps: NumericRange
    expected_value_after_cost_bps: NumericRange
    capacity_notional: float
    data_quality_status: DataQualityStatus
    model_version: str
    feature_version: str
    reason_codes: tuple[str, ...]

    def __post_init__(self) -> None:
        decision = _utc(self.decision_timestamp_utc, "decision timestamp")
        cutoff = _utc(self.data_cutoff_utc, "data cutoff")
        if cutoff > decision:
            raise ValueError("setup data cutoff cannot follow decision time")
        families = [item.family for item in self.evidence]
        if len(set(families)) != len(families):
            raise ValueError("a setup may contain at most one vote per family")
        if any(
            _utc(item.max_source_timestamp_utc, "evidence timestamp") > cutoff
            for item in self.evidence
        ):
            raise ValueError("setup evidence cannot follow the data cutoff")
        if not self.targets:
            raise ValueError("setup requires at least one market target")
        target_pairs = {
            (target.symbol, venue.lower()) for target in self.targets for venue in target.venues
        }
        if len({target.symbol for target in self.targets}) != len(self.targets):
            raise ValueError("setup market targets must be unique by symbol")
        if any((leg.symbol, leg.venue.lower()) not in target_pairs for leg in self.legs):
            raise ValueError("every setup leg must belong to a declared market target")
        if (
            not self.horizon.strip()
            or not self.model_version.strip()
            or not self.feature_version.strip()
        ):
            raise ValueError("setup requires horizon, model version, and feature version")
        if self.expected_cost_bps.low < 0:
            raise ValueError("expected cost range cannot be negative")
        if not math.isfinite(self.capacity_notional) or self.capacity_notional < 0:
            raise ValueError("setup capacity must be finite and non-negative")
        if not self.regimes or any(
            not name.strip() or not value.strip() for name, value in self.regimes
        ):
            raise ValueError("setup requires named regime domains and values")
        if len(set(name for name, _ in self.regimes)) != len(self.regimes):
            raise ValueError("setup regime domains must be unique")
        if self.action == SetupAction.WAIT:
            if not self.reason_codes:
                raise ValueError("WAIT requires at least one reason code")
            if self.legs:
                raise ValueError("WAIT cannot contain executable legs")
        elif not self.legs:
            raise ValueError("actionable setup requires execution legs")
        if self.action == SetupAction.LONG and any(leg.side != LegSide.BUY for leg in self.legs):
            raise ValueError("LONG setup legs must buy")
        if self.action == SetupAction.SHORT and any(leg.side != LegSide.SELL for leg in self.legs):
            raise ValueError("SHORT setup legs must sell")
        if self.action == SetupAction.ARBITRAGE:
            sides = {leg.side for leg in self.legs}
            if len(self.legs) < 2 or sides != {LegSide.BUY, LegSide.SELL}:
                raise ValueError("ARBITRAGE requires opposing buy and sell legs")
        if self.action != SetupAction.WAIT and (
            not self.entry_condition.strip()
            or not self.invalidation.strip()
            or not self.stop_or_hedge_logic.strip()
        ):
            raise ValueError("actionable setup requires entry, invalidation, and risk logic")


def _utc(value: datetime, name: str) -> datetime:
    if value.tzinfo is None:
        raise ValueError(f"{name} must be timezone-aware")
    return value.astimezone(UTC)
