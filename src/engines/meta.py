"""Portfolio-aware Meta Engine that can only reduce or reject approved setups."""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum

from src.engines.contracts import DataQualityStatus, SetupAction, SetupDecision


class EngineKind(StrEnum):
    DIRECTIONAL = "DIRECTIONAL"
    NEUTRAL = "NEUTRAL"
    RESEARCH = "RESEARCH"


@dataclass(frozen=True, slots=True)
class EngineCandidate:
    engine_id: str
    engine_kind: EngineKind
    setup: SetupDecision
    research_approved: bool

    def __post_init__(self) -> None:
        if not self.engine_id.strip():
            raise ValueError("meta candidate requires engine id")


@dataclass(frozen=True, slots=True)
class CorrelationPair:
    first_symbol: str
    second_symbol: str
    correlation: float

    def __post_init__(self) -> None:
        if (
            not self.first_symbol.strip()
            or not self.second_symbol.strip()
            or self.first_symbol == self.second_symbol
            or not math.isfinite(self.correlation)
            or not -1 <= self.correlation <= 1
        ):
            raise ValueError("invalid portfolio correlation pair")


@dataclass(frozen=True, slots=True)
class MetaPortfolioState:
    gross_exposure_notional: float
    exposure_by_symbol: tuple[tuple[str, float], ...]
    correlations: tuple[CorrelationPair, ...]
    available_risk_notional: float
    kill_switch_active: bool
    operational_healthy: bool
    portfolio_risk_approved: bool
    risk_reason: str

    def __post_init__(self) -> None:
        magnitudes = (
            self.gross_exposure_notional,
            self.available_risk_notional,
            *(exposure for _, exposure in self.exposure_by_symbol),
        )
        if any(not math.isfinite(value) or value < 0 for value in magnitudes):
            raise ValueError("meta portfolio exposures must be finite and non-negative")
        symbols = [symbol for symbol, _ in self.exposure_by_symbol]
        if any(not symbol.strip() for symbol in symbols) or len(set(symbols)) != len(symbols):
            raise ValueError("meta portfolio symbols must be named and unique")
        pair_keys = [
            tuple(sorted((pair.first_symbol, pair.second_symbol))) for pair in self.correlations
        ]
        if len(set(pair_keys)) != len(pair_keys):
            raise ValueError("meta portfolio correlation pairs must be unique")
        if not self.risk_reason.strip():
            raise ValueError("meta portfolio risk reason is required")


@dataclass(frozen=True, slots=True)
class MetaEngineConfig:
    maximum_setup_age_seconds: float = 30.0
    maximum_gross_exposure_notional: float = 1_000_000.0
    maximum_symbol_exposure_notional: float = 300_000.0
    maximum_correlated_exposure_notional: float = 500_000.0
    correlation_threshold: float = 0.7
    uncertainty_penalty: float = 0.5

    def __post_init__(self) -> None:
        if (
            not math.isfinite(self.maximum_setup_age_seconds)
            or self.maximum_setup_age_seconds <= 0
            or not math.isfinite(self.maximum_gross_exposure_notional)
            or self.maximum_gross_exposure_notional <= 0
            or not math.isfinite(self.maximum_symbol_exposure_notional)
            or self.maximum_symbol_exposure_notional <= 0
            or not math.isfinite(self.maximum_correlated_exposure_notional)
            or self.maximum_correlated_exposure_notional <= 0
            or not 0 <= self.correlation_threshold <= 1
            or not math.isfinite(self.uncertainty_penalty)
            or self.uncertainty_penalty < 0
        ):
            raise ValueError("invalid Meta Engine configuration")


@dataclass(frozen=True, slots=True)
class CandidateRanking:
    engine_id: str
    engine_kind: EngineKind
    action: SetupAction
    eligible: bool
    score: float | None
    maximum_allocation_notional: float
    reason: str


@dataclass(frozen=True, slots=True)
class MetaDecision:
    action: SetupAction
    decision_timestamp_utc: datetime
    selected_engine_id: str | None
    selected_setup: SetupDecision | None
    allocated_notional: float
    rankings: tuple[CandidateRanking, ...]
    reason_codes: tuple[str, ...]

    def __post_init__(self) -> None:
        _utc(self.decision_timestamp_utc, "meta decision timestamp")
        if self.action == SetupAction.WAIT:
            if self.selected_setup is not None or self.selected_engine_id is not None:
                raise ValueError("WAIT Meta Decision cannot select a setup")
            if not self.reason_codes or self.allocated_notional != 0:
                raise ValueError("WAIT Meta Decision requires reasons and zero allocation")
        else:
            if self.selected_setup is None or self.selected_engine_id is None:
                raise ValueError("actionable Meta Decision requires a selected setup")
            if self.selected_setup.action != self.action or self.allocated_notional <= 0:
                raise ValueError("Meta Decision cannot alter action or allocate zero")


def evaluate_meta_candidates(
    candidates: tuple[EngineCandidate, ...],
    *,
    decision_timestamp_utc: datetime,
    portfolio: MetaPortfolioState,
    config: MetaEngineConfig | None = None,
) -> MetaDecision:
    """Rank already-approved setups while enforcing global portfolio gates."""
    config = config or MetaEngineConfig()
    decision = _utc(decision_timestamp_utc, "meta decision timestamp")
    if len({candidate.engine_id for candidate in candidates}) != len(candidates):
        raise ValueError("Meta Engine candidate ids must be unique")
    global_reason = _global_gate_reason(portfolio)
    if global_reason is not None:
        return _wait(
            decision,
            tuple(_ineligible(candidate, global_reason) for candidate in candidates),
            global_reason,
        )

    rankings = tuple(
        _rank_candidate(candidate, decision=decision, portfolio=portfolio, config=config)
        for candidate in candidates
    )
    eligible = [ranking for ranking in rankings if ranking.eligible]
    if not eligible:
        return _wait(decision, rankings, "NO_ELIGIBLE_ENGINE_SETUP")
    candidate_by_id = {candidate.engine_id: candidate for candidate in candidates}
    if _has_directional_conflict(eligible, candidate_by_id):
        return _wait(decision, rankings, "CONFLICTING_DIRECTIONAL_SETUPS")
    selected_rank = sorted(
        eligible,
        key=lambda item: (
            -(item.score if item.score is not None else float("-inf")),
            item.engine_id,
        ),
    )[0]
    selected = candidate_by_id[selected_rank.engine_id]
    return MetaDecision(
        action=selected.setup.action,
        decision_timestamp_utc=decision,
        selected_engine_id=selected.engine_id,
        selected_setup=selected.setup,
        allocated_notional=selected_rank.maximum_allocation_notional,
        rankings=rankings,
        reason_codes=("BEST_ELIGIBLE_EDGE_AFTER_COST_AND_UNCERTAINTY",),
    )


def _rank_candidate(
    candidate: EngineCandidate,
    *,
    decision: datetime,
    portfolio: MetaPortfolioState,
    config: MetaEngineConfig,
) -> CandidateRanking:
    setup = candidate.setup
    if setup.action == SetupAction.WAIT:
        return _ineligible(candidate, "ENGINE_RETURNED_WAIT")
    if not candidate.research_approved:
        return _ineligible(candidate, "RESEARCH_PROMOTION_NOT_APPROVED")
    if setup.data_quality_status != DataQualityStatus.PASS:
        return _ineligible(candidate, "SETUP_DATA_QUALITY_NOT_PASS")
    if setup.decision_timestamp_utc.astimezone(UTC) > decision:
        return _ineligible(candidate, "SETUP_FROM_FUTURE")
    age = (decision - setup.data_cutoff_utc.astimezone(UTC)).total_seconds()
    if age < 0:
        return _ineligible(candidate, "SETUP_FROM_FUTURE")
    if age > config.maximum_setup_age_seconds:
        return _ineligible(candidate, "STALE_SETUP")
    if not _correlation_coverage_complete(setup, portfolio):
        return _ineligible(candidate, "MISSING_CORRELATION_EVIDENCE")
    allocation = _maximum_allocation(setup, portfolio=portfolio, config=config)
    if allocation <= 0:
        return _ineligible(candidate, "PORTFOLIO_EXPOSURE_LIMIT")
    value = setup.expected_value_after_cost_bps
    half_width = (value.high - value.low) / 2.0
    score = value.base - config.uncertainty_penalty * half_width
    if score <= 0 or value.low <= 0:
        return _ineligible(candidate, "NON_POSITIVE_RISK_ADJUSTED_EDGE")
    return CandidateRanking(
        engine_id=candidate.engine_id,
        engine_kind=candidate.engine_kind,
        action=setup.action,
        eligible=True,
        score=score,
        maximum_allocation_notional=allocation,
        reason="ELIGIBLE",
    )


def _maximum_allocation(
    setup: SetupDecision,
    *,
    portfolio: MetaPortfolioState,
    config: MetaEngineConfig,
) -> float:
    allocation = min(
        setup.capacity_notional,
        portfolio.available_risk_notional,
        max(
            0.0,
            config.maximum_gross_exposure_notional - portfolio.gross_exposure_notional,
        ),
    )
    exposure = dict(portfolio.exposure_by_symbol)
    symbols = {target.symbol for target in setup.targets}
    per_symbol_requested = allocation / len(symbols)
    per_symbol_room = min(
        max(0.0, config.maximum_symbol_exposure_notional - exposure.get(symbol, 0.0))
        for symbol in symbols
    )
    allocation = min(allocation, per_symbol_room * len(symbols))
    for symbol in symbols:
        correlated = sum(
            amount
            for existing_symbol, amount in exposure.items()
            if existing_symbol != symbol
            and abs(_correlation(symbol, existing_symbol, portfolio.correlations))
            >= config.correlation_threshold
        )
        correlated_room = max(0.0, config.maximum_correlated_exposure_notional - correlated)
        allocation = min(allocation, correlated_room * len(symbols))
    if per_symbol_requested <= 0:
        return 0.0
    return allocation


def _correlation(first: str, second: str, pairs: tuple[CorrelationPair, ...]) -> float:
    key = {first, second}
    for pair in pairs:
        if {pair.first_symbol, pair.second_symbol} == key:
            return pair.correlation
    return 0.0


def _correlation_coverage_complete(setup: SetupDecision, portfolio: MetaPortfolioState) -> bool:
    targets = {target.symbol for target in setup.targets}
    available_pairs = {
        frozenset((pair.first_symbol, pair.second_symbol)) for pair in portfolio.correlations
    }
    return all(
        existing_symbol in targets
        or amount == 0
        or frozenset((target, existing_symbol)) in available_pairs
        for target in targets
        for existing_symbol, amount in portfolio.exposure_by_symbol
    )


def _has_directional_conflict(
    eligible: list[CandidateRanking], candidates: dict[str, EngineCandidate]
) -> bool:
    directions: dict[str, set[SetupAction]] = {}
    for ranking in eligible:
        if ranking.action not in {SetupAction.LONG, SetupAction.SHORT}:
            continue
        setup = candidates[ranking.engine_id].setup
        for target in setup.targets:
            directions.setdefault(target.symbol, set()).add(ranking.action)
    return any(actions == {SetupAction.LONG, SetupAction.SHORT} for actions in directions.values())


def _ineligible(candidate: EngineCandidate, reason: str) -> CandidateRanking:
    return CandidateRanking(
        engine_id=candidate.engine_id,
        engine_kind=candidate.engine_kind,
        action=candidate.setup.action,
        eligible=False,
        score=None,
        maximum_allocation_notional=0.0,
        reason=reason,
    )


def _global_gate_reason(portfolio: MetaPortfolioState) -> str | None:
    if portfolio.kill_switch_active:
        return "GLOBAL_KILL_SWITCH_ACTIVE"
    if not portfolio.operational_healthy:
        return "GLOBAL_OPERATIONAL_HEALTH_FAILED"
    if not portfolio.portfolio_risk_approved:
        return f"GLOBAL_RISK_REJECTED:{portfolio.risk_reason}"
    if portfolio.available_risk_notional <= 0:
        return "NO_AVAILABLE_PORTFOLIO_RISK"
    return None


def _wait(
    decision: datetime,
    rankings: tuple[CandidateRanking, ...],
    reason: str,
) -> MetaDecision:
    return MetaDecision(
        action=SetupAction.WAIT,
        decision_timestamp_utc=decision,
        selected_engine_id=None,
        selected_setup=None,
        allocated_notional=0.0,
        rankings=rankings,
        reason_codes=(reason,),
    )


def _utc(value: datetime, name: str) -> datetime:
    if value.tzinfo is None:
        raise ValueError(f"{name} must be timezone-aware")
    return value.astimezone(UTC)
