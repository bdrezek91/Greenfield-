"""Durable, idempotent, fail-closed SHADOW decision producer tests."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import Mock

import pytest

from src.engines.contracts import (
    DataQualityStatus,
    LegSide,
    MarketTarget,
    NumericRange,
    SetupAction,
    SetupDecision,
    SetupLeg,
)
from src.engines.meta import CorrelationPair, EngineCandidate, EngineKind, MetaPortfolioState
from src.execution.shadow_loop import (
    DurableShadowQueue,
    ShadowEventLoop,
    ShadowIterationResult,
    ShadowQueueStatus,
)
from src.execution.shadow_producer import ShadowDecisionProducer
from src.execution.shadow_store import ShadowWorkStore, ShadowWorkStoreError

NOW = datetime(2026, 8, 24, 18, tzinfo=UTC)


def _setup(action: SetupAction = SetupAction.LONG) -> SetupDecision:
    if action is SetupAction.WAIT:
        legs: tuple[SetupLeg, ...] = ()
        targets = (MarketTarget("BTCUSDT", ("bybit",)),)
    elif action is SetupAction.ARBITRAGE:
        legs = (
            SetupLeg("BTCUSDT", "bybit", LegSide.BUY),
            SetupLeg("ETHUSDT", "binance", LegSide.SELL),
        )
        targets = (
            MarketTarget("BTCUSDT", ("bybit",)),
            MarketTarget("ETHUSDT", ("binance",)),
        )
    else:
        legs = (SetupLeg("BTCUSDT", "bybit", LegSide.BUY),)
        targets = (MarketTarget("BTCUSDT", ("bybit",)),)
    return SetupDecision(
        action=action,
        targets=targets,
        legs=legs,
        decision_timestamp_utc=NOW,
        data_cutoff_utc=NOW,
        horizon="15m",
        evidence=(),
        regimes=(("trend", "UP"),),
        entry_condition="approved point-in-time setup",
        invalidation="causal invalidation",
        stop_or_hedge_logic="bounded risk",
        expected_cost_bps=NumericRange(2, 3, 5),
        expected_value_after_cost_bps=NumericRange(4, 8, 12),
        capacity_notional=20_000.0,
        data_quality_status=DataQualityStatus.PASS,
        model_version="test-model-v1",
        feature_version="gold-v1",
        reason_codes=("APPROVED",) if action is not SetupAction.WAIT else ("NO_EDGE",),
    )


def _candidate(action: SetupAction = SetupAction.LONG) -> EngineCandidate:
    return EngineCandidate(
        engine_id="neutral-v1" if action is SetupAction.ARBITRAGE else "directional-v1",
        engine_kind=(
            EngineKind.NEUTRAL
            if action is SetupAction.ARBITRAGE
            else EngineKind.DIRECTIONAL
        ),
        setup=_setup(action),
        research_approved=True,
    )


def _portfolio(
    *,
    kill_switch: bool = False,
    correlations: tuple[CorrelationPair, ...] = (),
) -> MetaPortfolioState:
    return MetaPortfolioState(
        gross_exposure_notional=0.0,
        exposure_by_symbol=(),
        correlations=correlations,
        available_risk_notional=10_000.0,
        kill_switch_active=kill_switch,
        operational_healthy=True,
        portfolio_risk_approved=True,
        risk_reason="approved",
    )


def _producer(root: Path) -> ShadowDecisionProducer:
    store_dir = root / "work"
    store_dir.mkdir(parents=True, exist_ok=True)
    return ShadowDecisionProducer(
        queue=DurableShadowQueue(root / "queue.sqlite3"),
        store=ShadowWorkStore(store_dir, now_fn=lambda: NOW + timedelta(seconds=1)),
    )


def test_actionable_meta_decision_is_persisted_and_enqueued(tmp_path: Path) -> None:
    producer = _producer(tmp_path)
    result = producer.produce(
        observation_id="decision-1",
        candidates=(_candidate(),),
        portfolio=_portfolio(),
        decision_timestamp_utc=NOW,
        produced_at_utc=NOW + timedelta(seconds=1),
        equity=100_000.0,
    )

    assert result.enqueued
    assert result.work.meta.action is SetupAction.LONG
    assert len(result.work.proposals) == 1
    assert result.work.proposals[0].signed_notional == 10_000.0
    item = producer.queue.get("decision-1")
    assert item is not None and item.status is ShadowQueueStatus.PENDING
    assert producer.store.load(item.payload_uri) == result.work

    runtime = Mock()
    loop = ShadowEventLoop(
        queue=producer.queue,
        runtime=runtime,
        work_loader=producer.store.load,
        now_fn=lambda: NOW + timedelta(seconds=1),
    )
    assert loop.run_once() is ShadowIterationResult.PROCESSED
    runtime.observe.assert_called_once_with(
        result.work.meta,
        observation_id="decision-1",
        proposals=result.work.proposals,
        equity=100_000.0,
    )
    completed = producer.queue.get("decision-1")
    assert completed is not None and completed.status is ShadowQueueStatus.DONE


def test_restart_and_redelivery_are_idempotent(tmp_path: Path) -> None:
    first = _producer(tmp_path)
    arguments = {
        "observation_id": "decision-retry",
        "candidates": (_candidate(),),
        "portfolio": _portfolio(),
        "decision_timestamp_utc": NOW,
        "produced_at_utc": NOW + timedelta(seconds=1),
        "equity": 100_000.0,
    }
    assert first.produce(**arguments).enqueued
    restarted = _producer(tmp_path)
    assert not restarted.produce(**arguments).enqueued
    assert restarted.queue.snapshot()["pending"] == 1


def test_same_observation_id_with_different_content_fails(tmp_path: Path) -> None:
    producer = _producer(tmp_path)
    common = {
        "observation_id": "decision-conflict",
        "candidates": (_candidate(),),
        "portfolio": _portfolio(),
        "decision_timestamp_utc": NOW,
        "produced_at_utc": NOW + timedelta(seconds=1),
    }
    producer.produce(**common, equity=100_000.0)
    with pytest.raises(ShadowWorkStoreError, match="different content"):
        producer.produce(**common, equity=90_000.0)


def test_global_risk_gate_is_durable_wait_without_proposals(tmp_path: Path) -> None:
    producer = _producer(tmp_path)
    result = producer.produce(
        observation_id="decision-kill-switch",
        candidates=(_candidate(),),
        portfolio=_portfolio(kill_switch=True),
        decision_timestamp_utc=NOW,
        produced_at_utc=NOW + timedelta(seconds=1),
        equity=100_000.0,
    )
    assert result.work.meta.action is SetupAction.WAIT
    assert result.work.meta.reason_codes == ("GLOBAL_KILL_SWITCH_ACTIVE",)
    assert result.work.proposals == ()


def test_missing_multi_leg_correlation_evidence_becomes_wait(tmp_path: Path) -> None:
    producer = _producer(tmp_path)
    result = producer.produce(
        observation_id="decision-arb-no-correlation",
        candidates=(_candidate(SetupAction.ARBITRAGE),),
        portfolio=_portfolio(),
        decision_timestamp_utc=NOW,
        produced_at_utc=NOW + timedelta(seconds=1),
        equity=100_000.0,
    )
    assert result.work.meta.action is SetupAction.WAIT
    assert result.work.meta.reason_codes == ("MISSING_PROPOSAL_CORRELATION_EVIDENCE",)
    assert result.work.proposals == ()


def test_multi_leg_proposals_are_balanced_with_complete_correlation_evidence(
    tmp_path: Path,
) -> None:
    producer = _producer(tmp_path)
    result = producer.produce(
        observation_id="decision-arb-complete",
        candidates=(_candidate(SetupAction.ARBITRAGE),),
        portfolio=_portfolio(correlations=(CorrelationPair("BTCUSDT", "ETHUSDT", 0.8),)),
        decision_timestamp_utc=NOW,
        produced_at_utc=NOW + timedelta(seconds=1),
        equity=100_000.0,
    )
    assert result.work.meta.action is SetupAction.ARBITRAGE
    assert [item.signed_notional for item in result.work.proposals] == [10_000.0, -10_000.0]
    assert result.work.proposals[0].correlation_checked_symbols == ("ETHUSDT",)
    assert result.work.proposals[0].correlated_symbols == ("ETHUSDT",)
