"""Startup gate for the SHADOW service process (Cycle 2).

Mirrors src.execution.live_preflight's PreflightCheck/PreflightReport shape:
a named, structured pass/fail list that fails loudly with an actionable
reason rather than letting the service crash deep inside SQLite/journal
construction with a less legible traceback.

Restart-consistency (Cycle 6 remediation): `check_risk_state_and_audit_
consistency` catches the four ways the two durable stores that
`ShadowRuntime.resume()`/`initialize_new()` depend on can disagree after an
interrupted process - each one previously either silently mis-resumed or
surfaced only as an unhandled exception deep inside `ShadowRuntime` instead
of a named, documented preflight failure:

  1. the audit journal has records but no risk state file exists (e.g. the
     risk state was lost/deleted after being recorded) - `initialize_new()`
     would otherwise raise a bare `ValueError` trying to reinitialize over
     an existing audit trail;
  2. a risk state file exists but the audit journal has none (e.g. state
     was written but the journal was lost) - `ShadowRuntime.resume()`
     already raises `ShadowAuditError` for this, but only *after*
     preflight has already passed and the runtime is being constructed for
     real, which is too late for a clean, documented preflight-stage exit;
  3. both exist, load individually, but the journal's last recorded
     risk-state checksum does not match the risk state currently on disk
     (an unreconciled write - `resume()` also already checks this, same
     "too late" problem as above);
  4. either store is present but corrupt/malformed/partially written -
     caught explicitly here (via `PortfolioRiskStateError`/
     `ShadowAuditError`) rather than left to propagate as a raw traceback.

`src.execution.shadow_service.run_shadow_service` additionally wraps its
own `initialize_new`/`resume` call in a second, defense-in-depth catch (see
that module) in case state changes between this preflight and the actual
resume - so a failure here is never the last line of fail-closed defense,
just the first and clearest one.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

from src.execution.mode import LiveTradingBlockedError, TradingMode, resolve_trading_mode
from src.execution.shadow_runtime import ShadowAuditError, ShadowAuditJournal, ShadowSessionContext
from src.risk.portfolio_state_store import PortfolioRiskStateError, PortfolioRiskStateStore


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


def check_risk_state_and_audit_consistency(
    risk_state_path: Path, audit_journal_path: Path
) -> PreflightCheck:
    name = "risk_state_audit_consistency"

    risk_state_exists = risk_state_path.exists()
    risk_checksum: str | None = None
    if risk_state_exists:
        try:
            store = PortfolioRiskStateStore(risk_state_path)
            store.load()
            risk_checksum = store.checksum()
        except PortfolioRiskStateError as exc:
            return PreflightCheck(
                name, False, f"risk state at {risk_state_path} is present but corrupt: {exc}"
            )

    try:
        records = ShadowAuditJournal(audit_journal_path).verify()
    except ShadowAuditError as exc:
        return PreflightCheck(
            name,
            False,
            f"cannot evaluate risk-state/audit consistency: audit journal at "
            f"{audit_journal_path} failed integrity verification: {exc}",
        )

    if records and not risk_state_exists:
        return PreflightCheck(
            name,
            False,
            f"audit journal at {audit_journal_path} has {len(records)} record(s) but no risk "
            f"state exists at {risk_state_path} - refusing to silently reinitialize over an "
            "existing audit trail",
        )
    if risk_state_exists and not records:
        return PreflightCheck(
            name,
            False,
            f"risk state exists at {risk_state_path} but the audit journal at "
            f"{audit_journal_path} has no records - refusing to silently resume as if this "
            "were a fresh session",
        )
    if records and risk_state_exists:
        latest_journal_checksum = next(
            (
                record.risk_state_sha256
                for record in reversed(records)
                if record.risk_state_sha256 is not None
            ),
            None,
        )
        if latest_journal_checksum is not None and latest_journal_checksum != risk_checksum:
            return PreflightCheck(
                name,
                False,
                "audit journal's latest recorded risk-state checksum does not match the risk "
                f"state currently on disk (journal={latest_journal_checksum!r}, "
                f"on_disk={risk_checksum!r}) - state is unreconciled",
            )
    return PreflightCheck(
        name, True, "risk state and audit journal are consistent (or both legitimately absent)"
    )


def run_shadow_preflight(
    *,
    env: Mapping[str, str],
    context: ShadowSessionContext,
    queue_db_path: Path,
    work_store_dir: Path,
    risk_state_path: Path,
    audit_journal_path: Path,
) -> PreflightReport:
    return PreflightReport(
        checks=(
            check_trading_mode_is_shadow(env),
            check_directory_ready(queue_db_path.parent, "queue_db_directory"),
            check_directory_ready(work_store_dir, "work_store_directory"),
            check_directory_ready(risk_state_path.parent, "risk_state_directory"),
            check_directory_ready(audit_journal_path.parent, "audit_journal_directory"),
            check_context_matches_existing_audit(context, audit_journal_path),
            check_risk_state_and_audit_consistency(risk_state_path, audit_journal_path),
        )
    )
