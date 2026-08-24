"""Fail-closed MetaDecision producer for the durable no-order SHADOW queue."""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import UTC, datetime

from src.engines.contracts import LegSide, SetupAction
from src.engines.meta import (
    EngineCandidate,
    MetaDecision,
    MetaEngineConfig,
    MetaPortfolioState,
    evaluate_meta_candidates,
)
from src.execution.shadow_loop import DurableShadowQueue, ShadowWork
from src.execution.shadow_store import ShadowWorkStore, enqueue_shadow_work
from src.risk.portfolio_engine import PortfolioEntryProposal


@dataclass(frozen=True, slots=True)
class ShadowProducerConfig:
    committed_risk_fraction_per_leg: float = 0.005
    meta: MetaEngineConfig = MetaEngineConfig()

    def __post_init__(self) -> None:
        if (
            not math.isfinite(self.committed_risk_fraction_per_leg)
            or not 0 < self.committed_risk_fraction_per_leg <= 1
        ):
            raise ValueError("shadow producer committed risk must be in (0, 1]")


@dataclass(frozen=True, slots=True)
class ShadowProductionResult:
    work: ShadowWork
    enqueued: bool


class ShadowDecisionProducer:
    """Evaluate Meta candidates and durably hand one decision to SHADOW.

    The producer has no execution adapter. Repeating the same observation is
    idempotent; reusing its id for different content fails in ShadowWorkStore.
    """

    def __init__(
        self,
        *,
        queue: DurableShadowQueue,
        store: ShadowWorkStore,
        config: ShadowProducerConfig | None = None,
    ) -> None:
        self.queue = queue
        self.store = store
        self.config = config or ShadowProducerConfig()

    def produce(
        self,
        *,
        observation_id: str,
        candidates: tuple[EngineCandidate, ...],
        portfolio: MetaPortfolioState,
        decision_timestamp_utc: datetime,
        produced_at_utc: datetime,
        equity: float,
    ) -> ShadowProductionResult:
        decision_at = _utc(decision_timestamp_utc, "shadow decision timestamp")
        produced_at = _utc(produced_at_utc, "shadow produced timestamp")
        if produced_at < decision_at:
            raise ValueError("shadow work cannot be produced before its decision")
        if not math.isfinite(equity) or equity <= 0:
            raise ValueError("shadow producer equity must be finite and positive")

        meta = evaluate_meta_candidates(
            candidates,
            decision_timestamp_utc=decision_at,
            portfolio=portfolio,
            config=self.config.meta,
        )
        proposals: tuple[PortfolioEntryProposal, ...] = ()
        if meta.action is not SetupAction.WAIT:
            candidate = next(
                item for item in candidates if item.engine_id == meta.selected_engine_id
            )
            proposals = _build_proposals(
                observation_id=observation_id,
                meta=meta,
                candidate=candidate,
                portfolio=portfolio,
                committed_risk_fraction=self.config.committed_risk_fraction_per_leg,
                correlation_threshold=self.config.meta.correlation_threshold,
            )
            if not proposals:
                meta = MetaDecision(
                    action=SetupAction.WAIT,
                    decision_timestamp_utc=decision_at,
                    selected_engine_id=None,
                    selected_setup=None,
                    allocated_notional=0.0,
                    rankings=meta.rankings,
                    reason_codes=("MISSING_PROPOSAL_CORRELATION_EVIDENCE",),
                )

        work = ShadowWork(
            observation_id=observation_id,
            meta=meta,
            proposals=proposals,
            equity=equity,
        )
        enqueued = enqueue_shadow_work(
            queue=self.queue,
            store=self.store,
            work=work,
            written_at_utc=produced_at,
            available_at_utc=produced_at,
        )
        return ShadowProductionResult(work=work, enqueued=enqueued)


def _build_proposals(
    *,
    observation_id: str,
    meta: MetaDecision,
    candidate: EngineCandidate,
    portfolio: MetaPortfolioState,
    committed_risk_fraction: float,
    correlation_threshold: float,
) -> tuple[PortfolioEntryProposal, ...]:
    setup = meta.selected_setup
    if setup is None or meta.selected_engine_id is None:
        raise ValueError("actionable Meta decision must contain its selected setup")
    symbols = {leg.symbol for leg in setup.legs}
    existing = {symbol for symbol, amount in portfolio.exposure_by_symbol if amount > 0}
    checked_by_symbol: dict[str, tuple[str, ...]] = {}
    correlated_by_symbol: dict[str, tuple[str, ...]] = {}
    pairs = {
        frozenset((pair.first_symbol, pair.second_symbol)): pair.correlation
        for pair in portfolio.correlations
    }
    for symbol in symbols:
        checked = tuple(sorted((symbols | existing) - {symbol}))
        if any(frozenset((symbol, other)) not in pairs for other in checked):
            return ()
        checked_by_symbol[symbol] = checked
        correlated_by_symbol[symbol] = tuple(
            other
            for other in checked
            if abs(pairs[frozenset((symbol, other))]) >= correlation_threshold
        )

    per_leg_notional = (
        meta.allocated_notional
        if meta.action is SetupAction.ARBITRAGE
        else meta.allocated_notional / len(setup.legs)
    )
    return tuple(
        PortfolioEntryProposal(
            key=f"{observation_id}:leg-{index}",
            symbol=leg.symbol,
            venue=leg.venue,
            strategy=meta.selected_engine_id,
            engine=candidate.engine_kind.value.lower(),
            signed_notional=(
                per_leg_notional if leg.side is LegSide.BUY else -per_leg_notional
            ),
            committed_risk_fraction=committed_risk_fraction,
            correlation_checked_symbols=checked_by_symbol[leg.symbol],
            correlated_symbols=correlated_by_symbol[leg.symbol],
            proposed_at_utc=meta.decision_timestamp_utc,
        )
        for index, leg in enumerate(setup.legs)
    )


def _utc(value: datetime, name: str) -> datetime:
    if value.tzinfo is None:
        raise ValueError(f"{name} must be timezone-aware")
    return value.astimezone(UTC)
