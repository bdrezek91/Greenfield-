"""Evidence-to-Directional-to-Meta-to-durable-SHADOW vertical contract."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from src.engines.contracts import (
    ConfirmationFamily,
    DataQualityStatus,
    EngineGateState,
    FamilyEvidence,
    MarketTarget,
    NumericRange,
    SetupAction,
)
from src.engines.directional import DirectionalSetupRequest
from src.engines.meta import MetaPortfolioState
from src.execution.shadow_loop import DurableShadowQueue, ShadowQueueStatus
from src.execution.shadow_orchestrator import (
    DIRECTIONAL_SHADOW_SNAPSHOT_SCHEMA_VERSION,
    DirectionalShadowOrchestrator,
    DirectionalShadowSnapshot,
)
from src.execution.shadow_producer import ShadowDecisionProducer
from src.execution.shadow_runtime import ShadowSessionContext
from src.execution.shadow_store import ShadowWorkStore

NOW = datetime(2026, 8, 24, 18, tzinfo=UTC)
CONTEXT = ShadowSessionContext(
    session_id="shadow-session-1",
    dataset_fingerprint="dataset-sha256",
    code_commit="0123456789abcdef",
    config_fingerprint="config-sha256",
)


def _evidence(*, source_at: datetime = NOW) -> tuple[FamilyEvidence, ...]:
    return tuple(
        FamilyEvidence(
            family=family,
            score=0.8,
            confidence=0.9,
            quality=0.9,
            max_source_timestamp_utc=source_at,
            component_ids=(f"{family.value}-aggregate",),
            rationale=f"causal {family.value} evidence",
        )
        for family in ConfirmationFamily
    )


def _request(
    *,
    evidence: tuple[FamilyEvidence, ...] | None = None,
    promotion_eligible: bool = True,
) -> DirectionalSetupRequest:
    return DirectionalSetupRequest(
        target=MarketTarget("BTCUSDT", ("bybit",)),
        decision_timestamp_utc=NOW,
        data_cutoff_utc=NOW,
        horizon="15m-1h",
        evidence=evidence if evidence is not None else _evidence(),
        regimes=(("trend", "UPTREND"), ("liquidity", "LIQUID")),
        entry_condition="six independent families confirm",
        invalidation="causal family majority reverses",
        stop_logic="hard bounded stop",
        expected_gross_value_bps=NumericRange(20, 30, 45),
        expected_cost_bps=NumericRange(2, 4, 8),
        capacity_notional=20_000.0,
        data_quality_status=DataQualityStatus.PASS,
        model_version="directional-v1",
        feature_version="gold-v1",
        gates=EngineGateState(
            kill_switch_active=False,
            operational_healthy=True,
            promotion_eligible=promotion_eligible,
            promotion_state="CHALLENGER" if promotion_eligible else "RESEARCH_ONLY",
            risk_approved=True,
            risk_reason="approved",
        ),
    )


def _portfolio() -> MetaPortfolioState:
    return MetaPortfolioState(
        gross_exposure_notional=0.0,
        exposure_by_symbol=(),
        correlations=(),
        available_risk_notional=10_000.0,
        kill_switch_active=False,
        operational_healthy=True,
        portfolio_risk_approved=True,
        risk_reason="approved",
    )


def _orchestrator(root: Path, *, context: ShadowSessionContext = CONTEXT):
    store_dir = root / "work"
    store_dir.mkdir(parents=True, exist_ok=True)
    queue = DurableShadowQueue(root / "queue.sqlite3")
    store = ShadowWorkStore(store_dir, now_fn=lambda: NOW + timedelta(seconds=2))
    producer = ShadowDecisionProducer(queue=queue, store=store)
    return DirectionalShadowOrchestrator(context=context, producer=producer), queue, store


def _snapshot(**overrides: object) -> DirectionalShadowSnapshot:
    values: dict[str, object] = {
        "schema_version": DIRECTIONAL_SHADOW_SNAPSHOT_SCHEMA_VERSION,
        "observation_id": "btc-decision-1",
        "candidate_id": "directional-btc-v1",
        "session_context": CONTEXT,
        "request": _request(),
        "portfolio": _portfolio(),
        "research_approved": True,
        "equity": 100_000.0,
        "produced_at_utc": NOW + timedelta(seconds=1),
    }
    values.update(overrides)
    return DirectionalShadowSnapshot(**values)  # type: ignore[arg-type]


def test_six_family_snapshot_reaches_durable_shadow_queue(tmp_path: Path) -> None:
    orchestrator, queue, store = _orchestrator(tmp_path)
    result = orchestrator.produce(_snapshot())

    assert result.work.meta.action is SetupAction.LONG
    assert len(result.work.meta.selected_setup.evidence) == 6  # type: ignore[union-attr]
    assert len(result.work.proposals) == 1
    item = queue.get("btc-decision-1")
    assert item is not None and item.status is ShadowQueueStatus.PENDING
    assert store.load(item.payload_uri) == result.work


def test_promotion_gate_and_research_approval_each_force_wait(tmp_path: Path) -> None:
    orchestrator, _, _ = _orchestrator(tmp_path)
    promotion_wait = orchestrator.produce(
        _snapshot(
            observation_id="promotion-wait",
            request=_request(promotion_eligible=False),
        )
    )
    assert promotion_wait.work.meta.action is SetupAction.WAIT

    research_wait = orchestrator.produce(
        _snapshot(observation_id="research-wait", research_approved=False)
    )
    assert research_wait.work.meta.action is SetupAction.WAIT
    assert research_wait.work.proposals == ()


def test_context_mismatch_fails_before_any_enqueue(tmp_path: Path) -> None:
    orchestrator, queue, _ = _orchestrator(tmp_path)
    other = ShadowSessionContext(
        session_id="other",
        dataset_fingerprint=CONTEXT.dataset_fingerprint,
        code_commit=CONTEXT.code_commit,
        config_fingerprint=CONTEXT.config_fingerprint,
    )
    with pytest.raises(ValueError, match="context does not match"):
        orchestrator.produce(_snapshot(session_context=other))
    assert queue.snapshot()["pending"] == 0


def test_future_evidence_fails_before_any_enqueue(tmp_path: Path) -> None:
    orchestrator, queue, _ = _orchestrator(tmp_path)
    future_request = _request(evidence=_evidence(source_at=NOW + timedelta(seconds=1)))
    with pytest.raises(ValueError, match="evidence cannot follow data cutoff"):
        orchestrator.produce(_snapshot(request=future_request))
    assert queue.snapshot()["pending"] == 0


def test_snapshot_schema_and_clock_are_fail_closed() -> None:
    with pytest.raises(ValueError, match="schema"):
        _snapshot(schema_version=999)
    with pytest.raises(ValueError, match="cannot precede"):
        _snapshot(produced_at_utc=NOW - timedelta(seconds=1))


def test_stale_snapshot_fails_before_any_enqueue(tmp_path: Path) -> None:
    orchestrator, queue, _ = _orchestrator(tmp_path)
    with pytest.raises(ValueError, match="stale at production"):
        orchestrator.produce(
            _snapshot(produced_at_utc=NOW + timedelta(seconds=31))
        )
    assert queue.snapshot()["pending"] == 0
