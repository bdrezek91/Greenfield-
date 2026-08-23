"""Startup gate for the SHADOW service process (Cycle 2).

Mirrors src.execution.live_preflight's PreflightCheck/PreflightReport shape:
a named, structured pass/fail list that fails loudly with an actionable
reason rather than letting the service crash deep inside SQLite/journal
construction with a less legible traceback.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

from src.execution.mode import LiveTradingBlockedError, TradingMode, resolve_trading_mode
from src.execution.shadow_runtime import ShadowAuditError, ShadowAuditJournal, ShadowSessionContext


@dataclass(frozen=True)
class PreflightCheck:
    name: str
    passed: bool
    detail: str


@dataclass(frozen=True)
class PreflightReport:
    checks: tuple[PreflightCheck, ...]

    @property
    def all_passed(self) -> bool:
        return all(check.passed for check in self.checks)

    def failures(self) -> tuple[PreflightCheck, ...]:
        return tuple(check for check in self.checks if not check.passed)


def check_trading_mode_is_shadow(env: Mapping[str, str]) -> PreflightCheck:
    raw_mode = env.get("TRADING_MODE", "")
    try:
        mode = resolve_trading_mode(raw_mode, env)
    except (ValueError, LiveTradingBlockedError) as exc:
        return PreflightCheck("trading_mode", False, str(exc))
    if mode is not TradingMode.SHADOW:
        return PreflightCheck(
            "trading_mode", False, f"TRADING_MODE is {mode.value!r}, expected SHADOW"
        )
    return PreflightCheck("trading_mode", True, "TRADING_MODE=SHADOW")


def check_directory_ready(path: Path, name: str) -> PreflightCheck:
    try:
        path.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        return PreflightCheck(name, False, f"cannot create or access {path}: {exc}")
    if not path.is_dir():
        return PreflightCheck(name, False, f"{path} exists but is not a directory")
    return PreflightCheck(name, True, f"{path} is ready")


def check_context_matches_existing_audit(
    context: ShadowSessionContext, audit_journal_path: Path
) -> PreflightCheck:
    try:
        journal = ShadowAuditJournal(audit_journal_path)
        records = journal.verify()
    except ShadowAuditError as exc:
        return PreflightCheck(
            "audit_integrity", False, f"existing shadow audit failed integrity verification: {exc}"
        )
    if not records:
        return PreflightCheck(
            "audit_integrity", True, "no existing shadow audit; a new session will be initialized"
        )
    mismatched = [
        record
        for record in records
        if record.session_id != context.session_id
        or record.dataset_fingerprint != context.dataset_fingerprint
        or record.code_commit != context.code_commit
        or record.config_fingerprint != context.config_fingerprint
    ]
    if mismatched:
        return PreflightCheck(
            "audit_integrity",
            False,
            "existing shadow audit fingerprints do not match the configured session context "
            f"(session_id={context.session_id!r}, dataset={context.dataset_fingerprint!r}, "
            f"code={context.code_commit!r}, config={context.config_fingerprint!r})",
        )
    return PreflightCheck(
        "audit_integrity",
        True,
        f"{len(records)} existing shadow audit record(s) match the configured session context",
    )


def run_shadow_preflight(
    *,
    env: Mapping[str, str],
    context: ShadowSessionContext,
    queue_db_path: Path,
    work_store_dir: Path,
    audit_journal_path: Path,
) -> PreflightReport:
    return PreflightReport(
        checks=(
            check_trading_mode_is_shadow(env),
            check_directory_ready(queue_db_path.parent, "queue_db_directory"),
            check_directory_ready(work_store_dir, "work_store_directory"),
            check_directory_ready(audit_journal_path.parent, "audit_journal_directory"),
            check_context_matches_existing_audit(context, audit_journal_path),
        )
    )
