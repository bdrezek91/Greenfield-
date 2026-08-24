"""Versioned Directional evidence-to-SHADOW orchestration, with no execution path."""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import UTC, datetime

from src.engines.directional import (
    DirectionalEngineConfig,
    DirectionalSetupRequest,
    evaluate_directional_setup,
)
from src.engines.meta import EngineCandidate, EngineKind, MetaPortfolioState
from src.execution.shadow_producer import ShadowDecisionProducer, ShadowProductionResult
from src.execution.shadow_runtime import ShadowSessionContext

DIRECTIONAL_SHADOW_SNAPSHOT_SCHEMA_VERSION = 1


@dataclass(frozen=True, slots=True)
class DirectionalShadowSnapshot:
    schema_version: int
    observation_id: str
    candidate_id: str
    session_context: ShadowSessionContext
    request: DirectionalSetupRequest
    portfolio: MetaPortfolioState
    research_approved: bool
    equity: float
    produced_at_utc: datetime

    def __post_init__(self) -> None:
        if self.schema_version != DIRECTIONAL_SHADOW_SNAPSHOT_SCHEMA_VERSION:
            raise ValueError("unsupported directional SHADOW snapshot schema")
        if not self.observation_id.strip() or not self.candidate_id.strip():
            raise ValueError("directional SHADOW snapshot requires identifiers")
        produced = _utc(self.produced_at_utc, "directional SHADOW produced timestamp")
        decision = _utc(
            self.request.decision_timestamp_utc,
            "directional SHADOW decision timestamp",
        )
        if produced < decision:
            raise ValueError("directional SHADOW snapshot cannot precede its decision")
        if not math.isfinite(self.equity) or self.equity <= 0:
            raise ValueError("directional SHADOW equity must be finite and positive")


class DirectionalShadowOrchestrator:
    """Turn one immutable evidence snapshot into one durable SHADOW item."""

    def __init__(
        self,
        *,
        context: ShadowSessionContext,
        producer: ShadowDecisionProducer,
        directional_config: DirectionalEngineConfig | None = None,
    ) -> None:
        self.context = context
        self.producer = producer
        self.directional_config = directional_config or DirectionalEngineConfig()

    def produce(self, snapshot: DirectionalShadowSnapshot) -> ShadowProductionResult:
        if snapshot.session_context != self.context:
            raise ValueError("directional SHADOW snapshot context does not match the session")
        decision_at = _utc(
            snapshot.request.decision_timestamp_utc,
            "directional SHADOW decision timestamp",
        )
        produced_at = _utc(
            snapshot.produced_at_utc,
            "directional SHADOW produced timestamp",
        )
        production_lag = (produced_at - decision_at).total_seconds()
        if production_lag > self.directional_config.maximum_data_age_seconds:
            raise ValueError("directional SHADOW snapshot is stale at production time")
        setup = evaluate_directional_setup(snapshot.request, self.directional_config)
        candidate = EngineCandidate(
            engine_id=snapshot.candidate_id,
            engine_kind=EngineKind.DIRECTIONAL,
            setup=setup,
            research_approved=snapshot.research_approved,
        )
        return self.producer.produce(
            observation_id=snapshot.observation_id,
            candidates=(candidate,),
            portfolio=snapshot.portfolio,
            decision_timestamp_utc=snapshot.request.decision_timestamp_utc,
            produced_at_utc=snapshot.produced_at_utc,
            equity=snapshot.equity,
        )


def _utc(value: datetime, name: str) -> datetime:
    if value.tzinfo is None:
        raise ValueError(f"{name} must be timezone-aware")
    return value.astimezone(UTC)
