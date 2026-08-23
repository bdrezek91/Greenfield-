"""End-to-end wiring, resume, and exit-code tests for the SHADOW service."""

from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import Mock

import pytest

from src.engines.contracts import SetupAction
from src.engines.meta import MetaDecision
from src.execution.shadow_loop import DurableShadowQueue, ShadowLoopFatalError, ShadowWork
from src.execution.shadow_runtime import (
    ShadowAuditError,
    ShadowAuditJournal,
    ShadowRuntime,
    ShadowSessionContext,
)
from src.execution.shadow_service import (
    SHADOW_EXIT_FATAL,
    SHADOW_EXIT_OK,
    SHADOW_EXIT_PREFLIGHT_FAILED,
    SHADOW_EXIT_STATE_RECONCILIATION_FAILED,
    _run_until_stopped,
    run_shadow_service,
)
from src.execution.shadow_store import ShadowWorkStore, enqueue_shadow_work

NOW = datetime(2026, 8, 23, 18, tzinfo=UTC)


def _context() -> ShadowSessionContext:
    return ShadowSessionContext(
        session_id="shadow-20260823",
        dataset_fingerprint="dataset-sha256",
        code_commit="d62b191",
        config_fingerprint="config-sha256",
    )


def _paths(tmp_path: Path) -> dict[str, Path]:
    return {
        "queue_db_path": tmp_path / "queue.sqlite3",
        "work_store_dir": tmp_path / "work",
        "risk_state_path": tmp_path / "risk-state.json",
        "audit_journal_path": tmp_path / "audit.jsonl",
        "health_path": tmp_path / "health.json",
    }


def test_preflight_failure_returns_preflight_exit_code(tmp_path: Path) -> None:
    exit_code = run_shadow_service(
        context=_context(),
        env={"TRADING_MODE": "PAPER"},
        shutdown_requested=lambda: True,
        now_fn=lambda: NOW,
        **_paths(tmp_path),
    )
    assert exit_code == SHADOW_EXIT_PREFLIGHT_FAILED
    assert not (tmp_path / "risk-state.json").exists()


def test_initializes_a_new_session_and_shuts_down_cleanly(tmp_path: Path) -> None:
    paths = _paths(tmp_path)
    exit_code = run_shadow_service(
        context=_context(),
        env={"TRADING_MODE": "SHADOW"},
        shutdown_requested=lambda: True,
        now_fn=lambda: NOW,
        **paths,
    )
    assert exit_code == SHADOW_EXIT_OK
    assert paths["risk_state_path"].exists()
    journal = ShadowAuditJournal(paths["audit_journal_path"])
    records = journal.verify()
    assert len(records) == 1
    assert records[0].action == "INITIALIZE"


def test_resumes_an_existing_session_without_reinitializing(tmp_path: Path) -> None:
    paths = _paths(tmp_path)
    run_shadow_service(
        context=_context(),
        env={"TRADING_MODE": "SHADOW"},
        shutdown_requested=lambda: True,
        now_fn=lambda: NOW,
        **paths,
    )
    exit_code = run_shadow_service(
        context=_context(),
        env={"TRADING_MODE": "SHADOW"},
        shutdown_requested=lambda: True,
        now_fn=lambda: NOW,
        **paths,
    )
    assert exit_code == SHADOW_EXIT_OK
    journal = ShadowAuditJournal(paths["audit_journal_path"])
    records = journal.verify()
    assert len(records) == 1  # resume must not append a second INITIALIZE


def test_restart_with_lost_risk_state_fails_closed_at_preflight(tmp_path: Path) -> None:
    """The audit journal survives but the risk state file is lost between
    runs (disk issue, manual deletion, ...): the service must refuse to
    silently reinitialize over the existing audit trail, and must not raise
    an unhandled traceback doing so."""
    paths = _paths(tmp_path)
    run_shadow_service(
        context=_context(),
        env={"TRADING_MODE": "SHADOW"},
        shutdown_requested=lambda: True,
        now_fn=lambda: NOW,
        **paths,
    )
    assert paths["risk_state_path"].exists()
    paths["risk_state_path"].unlink()

    exit_code = run_shadow_service(
        context=_context(),
        env={"TRADING_MODE": "SHADOW"},
        shutdown_requested=lambda: True,
        now_fn=lambda: NOW,
        **paths,
    )

    assert exit_code == SHADOW_EXIT_PREFLIGHT_FAILED


def test_startup_reconciliation_failure_after_preflight_is_a_documented_exit_code(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Defense-in-depth: even if a resume/initialize failure somehow slips
    past preflight (e.g. state changes in the gap between the two, or a
    future preflight-check gap), run_shadow_service must still return a
    documented exit code rather than let the exception propagate out of
    main()."""
    paths = _paths(tmp_path)
    run_shadow_service(
        context=_context(),
        env={"TRADING_MODE": "SHADOW"},
        shutdown_requested=lambda: True,
        now_fn=lambda: NOW,
        **paths,
    )  # a consistent, preflight-passing session now exists on disk

    def _boom(*args: object, **kwargs: object) -> None:
        raise ShadowAuditError("simulated race: state changed after preflight passed")

    monkeypatch.setattr(ShadowRuntime, "resume", staticmethod(_boom))

    exit_code = run_shadow_service(
        context=_context(),
        env={"TRADING_MODE": "SHADOW"},
        shutdown_requested=lambda: True,
        now_fn=lambda: NOW,
        **paths,
    )

    assert exit_code == SHADOW_EXIT_STATE_RECONCILIATION_FAILED


def test_processes_a_pre_enqueued_work_item_end_to_end(tmp_path: Path) -> None:
    paths = _paths(tmp_path)
    run_shadow_service(
        context=_context(),
        env={"TRADING_MODE": "SHADOW"},
        shutdown_requested=lambda: True,
        now_fn=lambda: NOW,
        **paths,
    )

    store = ShadowWorkStore(paths["work_store_dir"], now_fn=lambda: NOW)
    queue = DurableShadowQueue(paths["queue_db_path"])
    work = ShadowWork(
        observation_id="observation-1",
        meta=MetaDecision(
            action=SetupAction.WAIT,
            decision_timestamp_utc=NOW,
            selected_engine_id=None,
            selected_setup=None,
            allocated_notional=0.0,
            rankings=(),
            reason_codes=("NO_EDGE",),
        ),
        proposals=(),
        equity=100_000.0,
    )
    enqueue_shadow_work(
        queue=queue, store=store, work=work, written_at_utc=NOW, available_at_utc=NOW
    )

    calls = {"count": 0}

    def stop_after_one() -> bool:
        calls["count"] += 1
        return calls["count"] > 1

    exit_code = run_shadow_service(
        context=_context(),
        env={"TRADING_MODE": "SHADOW"},
        shutdown_requested=stop_after_one,
        now_fn=lambda: NOW,
        **paths,
    )
    assert exit_code == SHADOW_EXIT_OK

    reopened_queue = DurableShadowQueue(paths["queue_db_path"])
    assert reopened_queue.snapshot()["done"] == 1
    journal = ShadowAuditJournal(paths["audit_journal_path"])
    records = journal.verify()
    assert any(record.observation_id == "observation-1" for record in records)


def test_run_until_stopped_maps_fatal_loop_error_to_fatal_exit_code() -> None:
    loop = Mock()
    loop.run_until.side_effect = ShadowLoopFatalError("boom")
    assert _run_until_stopped(loop, lambda: True) == SHADOW_EXIT_FATAL


def test_run_until_stopped_returns_ok_on_clean_completion() -> None:
    loop = Mock()
    assert _run_until_stopped(loop, lambda: True) == SHADOW_EXIT_OK
