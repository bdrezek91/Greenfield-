"""Startup-gate tests for the SHADOW service preflight checks."""

from datetime import UTC, datetime, timedelta
from pathlib import Path

from src.execution.mode import TradingMode
from src.execution.shadow_preflight import (
    check_context_matches_existing_audit,
    check_directory_ready,
    check_risk_state_and_audit_consistency,
    check_trading_mode_is_shadow,
    run_shadow_preflight,
)
from src.execution.shadow_runtime import ShadowAuditJournal, ShadowRuntime, ShadowSessionContext
from src.risk.portfolio_engine import PortfolioRiskConfig, PortfolioRiskEngine
from src.risk.portfolio_state_store import PortfolioRiskStateStore

NOW = datetime(2026, 8, 23, 18, tzinfo=UTC)


def _context(**overrides: str) -> ShadowSessionContext:
    fields = {
        "session_id": "shadow-20260823",
        "dataset_fingerprint": "dataset-sha256",
        "code_commit": "d62b191",
        "config_fingerprint": "config-sha256",
    }
    fields.update(overrides)
    return ShadowSessionContext(**fields)


def test_trading_mode_check_requires_shadow() -> None:
    assert check_trading_mode_is_shadow({"TRADING_MODE": "SHADOW"}).passed
    assert not check_trading_mode_is_shadow({"TRADING_MODE": "PAPER"}).passed
    assert not check_trading_mode_is_shadow({"TRADING_MODE": "not-a-mode"}).passed
    assert not check_trading_mode_is_shadow({}).passed


def test_directory_ready_creates_missing_directories(tmp_path: Path) -> None:
    target = tmp_path / "a" / "b" / "c"
    result = check_directory_ready(target, "some_directory")
    assert result.passed
    assert target.is_dir()


def test_directory_ready_fails_when_parent_is_a_file(tmp_path: Path) -> None:
    blocking_file = tmp_path / "not-a-directory"
    blocking_file.write_text("x", encoding="utf-8")
    result = check_directory_ready(blocking_file / "subdir", "some_directory")
    assert not result.passed


def test_audit_check_passes_when_no_audit_exists(tmp_path: Path) -> None:
    result = check_context_matches_existing_audit(_context(), tmp_path / "audit.jsonl")
    assert result.passed
    assert "no existing" in result.detail


def test_audit_check_passes_when_context_matches_existing_audit(tmp_path: Path) -> None:
    path = tmp_path / "audit.jsonl"
    journal = ShadowAuditJournal(path)
    store = PortfolioRiskStateStore(tmp_path / "risk-state.json")
    context = _context()
    ShadowRuntime.initialize_new(
        trading_mode=TradingMode.SHADOW,
        context=context,
        risk_engine=PortfolioRiskEngine(PortfolioRiskConfig()),
        risk_store=store,
        journal=journal,
        initialized_at_utc=NOW,
    )

    result = check_context_matches_existing_audit(context, path)
    assert result.passed


def test_audit_check_fails_when_context_diverges_from_existing_audit(tmp_path: Path) -> None:
    path = tmp_path / "audit.jsonl"
    journal = ShadowAuditJournal(path)
    store = PortfolioRiskStateStore(tmp_path / "risk-state.json")
    ShadowRuntime.initialize_new(
        trading_mode=TradingMode.SHADOW,
        context=_context(),
        risk_engine=PortfolioRiskEngine(PortfolioRiskConfig()),
        risk_store=store,
        journal=journal,
        initialized_at_utc=NOW,
    )

    result = check_context_matches_existing_audit(
        _context(dataset_fingerprint="different-dataset"), path
    )
    assert not result.passed


def test_audit_check_fails_closed_on_tampered_journal(tmp_path: Path) -> None:
    path = tmp_path / "audit.jsonl"
    journal = ShadowAuditJournal(path)
    store = PortfolioRiskStateStore(tmp_path / "risk-state.json")
    ShadowRuntime.initialize_new(
        trading_mode=TradingMode.SHADOW,
        context=_context(),
        risk_engine=PortfolioRiskEngine(PortfolioRiskConfig()),
        risk_store=store,
        journal=journal,
        initialized_at_utc=NOW,
    )
    path.write_text(path.read_text(encoding="utf-8") + "not json\n", encoding="utf-8")

    result = check_context_matches_existing_audit(_context(), path)
    assert not result.passed
    assert "integrity" in result.detail


def test_run_shadow_preflight_aggregates_all_checks(tmp_path: Path) -> None:
    report = run_shadow_preflight(
        env={"TRADING_MODE": "SHADOW"},
        context=_context(),
        queue_db_path=tmp_path / "queue" / "queue.sqlite3",
        work_store_dir=tmp_path / "work",
        risk_state_path=tmp_path / "risk-state.json",
        audit_journal_path=tmp_path / "audit.jsonl",
    )
    assert report.all_passed
    assert len(report.checks) == 7
    assert (tmp_path / "queue").is_dir()
    assert (tmp_path / "work").is_dir()


def test_run_shadow_preflight_reports_failures(tmp_path: Path) -> None:
    report = run_shadow_preflight(
        env={"TRADING_MODE": "PAPER"},
        context=_context(),
        queue_db_path=tmp_path / "queue.sqlite3",
        work_store_dir=tmp_path / "work",
        risk_state_path=tmp_path / "risk-state.json",
        audit_journal_path=tmp_path / "audit.jsonl",
    )
    assert not report.all_passed
    assert any(check.name == "trading_mode" for check in report.failures())


def _initialize(tmp_path: Path, *, context: ShadowSessionContext | None = None) -> None:
    journal = ShadowAuditJournal(tmp_path / "audit.jsonl")
    store = PortfolioRiskStateStore(tmp_path / "risk-state.json")
    ShadowRuntime.initialize_new(
        trading_mode=TradingMode.SHADOW,
        context=context or _context(),
        risk_engine=PortfolioRiskEngine(PortfolioRiskConfig()),
        risk_store=store,
        journal=journal,
        initialized_at_utc=NOW,
    )


def test_risk_state_consistency_passes_when_both_absent(tmp_path: Path) -> None:
    result = check_risk_state_and_audit_consistency(
        tmp_path / "risk-state.json", tmp_path / "audit.jsonl"
    )
    assert result.passed


def test_risk_state_consistency_passes_when_both_present_and_reconciled(tmp_path: Path) -> None:
    _initialize(tmp_path)
    result = check_risk_state_and_audit_consistency(
        tmp_path / "risk-state.json", tmp_path / "audit.jsonl"
    )
    assert result.passed


def test_risk_state_consistency_fails_when_audit_exists_but_risk_state_missing(
    tmp_path: Path,
) -> None:
    _initialize(tmp_path)
    (tmp_path / "risk-state.json").unlink()

    result = check_risk_state_and_audit_consistency(
        tmp_path / "risk-state.json", tmp_path / "audit.jsonl"
    )
    assert not result.passed
    assert "no risk state exists" in result.detail


def test_risk_state_consistency_fails_when_risk_state_exists_but_audit_missing(
    tmp_path: Path,
) -> None:
    _initialize(tmp_path)
    (tmp_path / "audit.jsonl").unlink()

    result = check_risk_state_and_audit_consistency(
        tmp_path / "risk-state.json", tmp_path / "audit.jsonl"
    )
    assert not result.passed
    assert "audit journal" in result.detail and "no records" in result.detail


def test_risk_state_consistency_fails_when_checksums_are_unreconciled(tmp_path: Path) -> None:
    _initialize(tmp_path)
    # simulate an unreconciled write: risk state moves on without a matching
    # audit record ever being appended for it
    store = PortfolioRiskStateStore(tmp_path / "risk-state.json")
    engine = PortfolioRiskEngine(PortfolioRiskConfig())
    store.save(engine.snapshot(), saved_at_utc=NOW + timedelta(seconds=1))

    result = check_risk_state_and_audit_consistency(
        tmp_path / "risk-state.json", tmp_path / "audit.jsonl"
    )
    assert not result.passed
    assert "unreconciled" in result.detail


def test_risk_state_consistency_fails_closed_on_corrupt_risk_state(tmp_path: Path) -> None:
    _initialize(tmp_path)
    (tmp_path / "risk-state.json").write_text("not json", encoding="utf-8")

    result = check_risk_state_and_audit_consistency(
        tmp_path / "risk-state.json", tmp_path / "audit.jsonl"
    )
    assert not result.passed
    assert "corrupt" in result.detail


def test_risk_state_consistency_fails_closed_on_corrupt_audit_journal(tmp_path: Path) -> None:
    _initialize(tmp_path)
    audit_path = tmp_path / "audit.jsonl"
    audit_path.write_text(audit_path.read_text(encoding="utf-8") + "not json\n", encoding="utf-8")

    result = check_risk_state_and_audit_consistency(tmp_path / "risk-state.json", audit_path)
    assert not result.passed
    assert "integrity verification" in result.detail


def test_run_shadow_preflight_fails_on_risk_state_audit_inconsistency(tmp_path: Path) -> None:
    _initialize(tmp_path)
    (tmp_path / "risk-state.json").unlink()

    report = run_shadow_preflight(
        env={"TRADING_MODE": "SHADOW"},
        context=_context(),
        queue_db_path=tmp_path / "queue.sqlite3",
        work_store_dir=tmp_path / "work",
        risk_state_path=tmp_path / "risk-state.json",
        audit_journal_path=tmp_path / "audit.jsonl",
    )
    assert not report.all_passed
    assert any(check.name == "risk_state_audit_consistency" for check in report.failures())
