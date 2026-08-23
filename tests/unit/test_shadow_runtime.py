"""SHADOW observes setups and virtual risk but has no execution path."""

import json
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path

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
from src.engines.meta import MetaDecision
from src.execution.mode import TradingMode
from src.execution.shadow_runtime import (
    ShadowAuditError,
    ShadowAuditJournal,
    ShadowRuntime,
    ShadowSessionContext,
    ShadowStatus,
)
from src.risk.portfolio_engine import (
    PortfolioEntryProposal,
    PortfolioRiskConfig,
    PortfolioRiskEngine,
)
from src.risk.portfolio_state_store import PortfolioRiskStateStore

NOW = datetime(2026, 8, 23, 16, tzinfo=UTC)


def _context() -> ShadowSessionContext:
    return ShadowSessionContext(
        session_id="shadow-20260823",
        dataset_fingerprint="dataset-sha256",
        code_commit="886a79d",
        config_fingerprint="config-sha256",
    )


def _setup(action: SetupAction = SetupAction.LONG) -> SetupDecision:
    side = LegSide.BUY if action == SetupAction.LONG else LegSide.SELL
    return SetupDecision(
        action=action,
        targets=(MarketTarget("BTCUSDT", ("bybit",)),),
        legs=(SetupLeg("BTCUSDT", "bybit", side),),
        decision_timestamp_utc=NOW,
        data_cutoff_utc=NOW,
        horizon="15m",
        evidence=(),
        regimes=(("trend", "up"),),
        entry_condition="confirmed setup",
        invalidation="structure break",
        stop_or_hedge_logic="fixed risk stop",
        expected_cost_bps=NumericRange(2, 3, 5),
        expected_value_after_cost_bps=NumericRange(4, 8, 12),
        capacity_notional=20_000.0,
        data_quality_status=DataQualityStatus.PASS,
        model_version="directional-v1",
        feature_version="features-v1",
        reason_codes=("APPROVED",),
    )


def _meta(action: SetupAction = SetupAction.LONG) -> MetaDecision:
    if action == SetupAction.WAIT:
        return MetaDecision(
            action=SetupAction.WAIT,
            decision_timestamp_utc=NOW,
            selected_engine_id=None,
            selected_setup=None,
            allocated_notional=0.0,
            rankings=(),
            reason_codes=("NO_EDGE",),
        )
    return MetaDecision(
        action=action,
        decision_timestamp_utc=NOW,
        selected_engine_id="directional-v1",
        selected_setup=_setup(action),
        allocated_notional=20_000.0,
        rankings=(),
        reason_codes=("BEST_EDGE",),
    )


def _proposal(key: str = "btc-long") -> PortfolioEntryProposal:
    return PortfolioEntryProposal(
        key=key,
        symbol="BTCUSDT",
        venue="bybit",
        strategy="directional-v1",
        engine="directional",
        signed_notional=20_000.0,
        committed_risk_fraction=0.01,
        correlation_checked_symbols=(),
        correlated_symbols=(),
        proposed_at_utc=NOW,
    )


def _new_runtime(
    tmp_path: Path,
    *,
    config: PortfolioRiskConfig | None = None,
) -> tuple[ShadowRuntime, PortfolioRiskStateStore, ShadowAuditJournal]:
    store = PortfolioRiskStateStore(tmp_path / "risk-state.json")
    journal = ShadowAuditJournal(tmp_path / "shadow-audit.jsonl")
    runtime = ShadowRuntime.initialize_new(
        trading_mode=TradingMode.SHADOW,
        context=_context(),
        risk_engine=PortfolioRiskEngine(config),
        risk_store=store,
        journal=journal,
        initialized_at_utc=NOW,
    )
    return runtime, store, journal


def test_shadow_runtime_rejects_every_non_shadow_mode(tmp_path: Path) -> None:
    store = PortfolioRiskStateStore(tmp_path / "state.json")
    journal = ShadowAuditJournal(tmp_path / "audit.jsonl")
    for mode in (
        TradingMode.RESEARCH,
        TradingMode.BACKTEST,
        TradingMode.PAPER,
        TradingMode.LIVE,
    ):
        with pytest.raises(ValueError, match="requires TradingMode.SHADOW"):
            ShadowRuntime(
                trading_mode=mode,
                context=_context(),
                risk_engine=PortfolioRiskEngine(),
                risk_store=store,
                journal=journal,
            )


def test_initialize_wrong_mode_does_not_create_state(tmp_path: Path) -> None:
    store = PortfolioRiskStateStore(tmp_path / "state.json")
    with pytest.raises(ValueError, match="requires TradingMode.SHADOW"):
        ShadowRuntime.initialize_new(
            trading_mode=TradingMode.PAPER,
            context=_context(),
            risk_engine=PortfolioRiskEngine(),
            risk_store=store,
            journal=ShadowAuditJournal(tmp_path / "audit.jsonl"),
            initialized_at_utc=NOW,
        )
    assert store.load() is None


def test_wait_is_audited_without_mutating_risk_state(tmp_path: Path) -> None:
    runtime, store, journal = _new_runtime(tmp_path)
    before = store.checksum()

    record = runtime.observe(
        _meta(SetupAction.WAIT),
        observation_id="wait-1",
        proposals=(),
        equity=100_000.0,
    )

    assert record.status == ShadowStatus.WAIT
    assert record.reason_codes == ("NO_EDGE",)
    assert store.checksum() == before
    assert journal.verify()[-1] == record
    assert journal.verify()[0].status == ShadowStatus.INITIALIZED


def test_actionable_setup_opens_only_virtual_exposure_and_resumes(tmp_path: Path) -> None:
    runtime, store, journal = _new_runtime(tmp_path)

    record = runtime.observe(
        _meta(),
        observation_id="long-1",
        proposals=(_proposal(),),
        equity=100_000.0,
    )

    assert record.status == ShadowStatus.ELIGIBLE_NO_ORDER
    assert record.reason_codes == ("SHADOW_ONLY_NO_ORDER_SUBMISSION",)
    assert record.risk_state_sha256 == store.checksum()
    assert runtime.risk_engine.gross_exposure == 20_000.0
    resumed = ShadowRuntime.resume(
        trading_mode=TradingMode.SHADOW,
        context=_context(),
        risk_store=store,
        journal=journal,
        risk_config=PortfolioRiskConfig(),
    )
    assert resumed.risk_engine.positions[0].key == "btc-long"


def test_portfolio_rejection_is_audited_without_state_change(tmp_path: Path) -> None:
    runtime, store, _ = _new_runtime(
        tmp_path,
        config=PortfolioRiskConfig(maximum_symbol_exposure_multiple=0.00001),
    )
    before = store.checksum()

    record = runtime.observe(
        _meta(),
        observation_id="blocked-1",
        proposals=(_proposal(),),
        equity=100_000.0,
    )

    assert record.status == ShadowStatus.RISK_REJECTED
    assert "NO_PORTFOLIO_RISK_CAPACITY" in record.reason_codes
    assert runtime.risk_engine.positions == ()
    assert store.checksum() == before


def test_virtual_close_persists_and_is_audited(tmp_path: Path) -> None:
    runtime, store, journal = _new_runtime(tmp_path)
    runtime.observe(
        _meta(), observation_id="long-1", proposals=(_proposal(),), equity=100_000.0
    )

    close = runtime.close_virtual(
        observation_id="close-1",
        realized_pnl_by_key=(("btc-long", -100.0),),
        closed_at_utc=NOW,
    )

    assert close.status == ShadowStatus.VIRTUAL_CLOSE
    assert runtime.risk_engine.positions == ()
    assert close.risk_state_sha256 == store.checksum()
    assert len(journal.verify()) == 3


def test_journal_rejects_duplicates_and_detects_tampering(tmp_path: Path) -> None:
    runtime, _, journal = _new_runtime(tmp_path)
    runtime.observe(
        _meta(SetupAction.WAIT),
        observation_id="same",
        proposals=(),
        equity=100_000.0,
    )
    with pytest.raises(ShadowAuditError, match="duplicate"):
        runtime.observe(
            _meta(SetupAction.WAIT),
            observation_id="same",
            proposals=(),
            equity=100_000.0,
        )

    lines = journal.path.read_text(encoding="utf-8").splitlines()
    envelope = json.loads(lines[-1])
    envelope["record"]["reason_codes"] = ["TAMPERED"]
    lines[-1] = json.dumps(envelope)
    journal.path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    with pytest.raises(ShadowAuditError, match="line 2"):
        ShadowAuditJournal(journal.path)


def test_resume_fails_closed_when_state_and_audit_diverge(tmp_path: Path) -> None:
    runtime, store, journal = _new_runtime(tmp_path)
    runtime.observe(
        _meta(), observation_id="long-1", proposals=(_proposal(),), equity=100_000.0
    )
    store.save(PortfolioRiskEngine().snapshot(), saved_at_utc=NOW)

    with pytest.raises(ShadowAuditError, match="not reconciled"):
        ShadowRuntime.resume(
            trading_mode=TradingMode.SHADOW,
            context=_context(),
            risk_store=store,
            journal=journal,
            risk_config=PortfolioRiskConfig(),
        )


def test_resume_rejects_a_different_research_context(tmp_path: Path) -> None:
    runtime, store, journal = _new_runtime(tmp_path)
    runtime.observe(
        _meta(SetupAction.WAIT),
        observation_id="wait-1",
        proposals=(),
        equity=100_000.0,
    )

    with pytest.raises(ShadowAuditError, match="context does not match"):
        ShadowRuntime.resume(
            trading_mode=TradingMode.SHADOW,
            context=replace(_context(), code_commit="different-commit"),
            risk_store=store,
            journal=journal,
            risk_config=PortfolioRiskConfig(),
        )


def test_actionable_proposals_must_exactly_match_selected_legs(tmp_path: Path) -> None:
    runtime, _, _ = _new_runtime(tmp_path)
    wrong = PortfolioEntryProposal(
        key="wrong",
        symbol="ETHUSDT",
        venue="bybit",
        strategy="directional-v1",
        engine="directional",
        signed_notional=20_000.0,
        committed_risk_fraction=0.01,
        correlation_checked_symbols=(),
        correlated_symbols=(),
        proposed_at_utc=NOW,
    )

    with pytest.raises(ValueError, match="do not match"):
        runtime.observe(
            _meta(),
            observation_id="wrong-leg",
            proposals=(wrong,),
            equity=100_000.0,
        )
