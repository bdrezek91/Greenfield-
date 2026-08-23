"""No-order shadow coordinator with durable risk state and chained audit."""

from __future__ import annotations

import hashlib
import hmac
import json
import math
import os
import threading
from collections import Counter
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from typing import Any

from src.engines.contracts import LegSide, SetupAction
from src.engines.meta import MetaDecision
from src.execution.mode import TradingMode
from src.risk.portfolio_engine import (
    PortfolioEntryProposal,
    PortfolioRiskConfig,
    PortfolioRiskDecision,
    PortfolioRiskEngine,
)
from src.risk.portfolio_state_store import PortfolioRiskStateStore


class ShadowStatus(StrEnum):
    INITIALIZED = "INITIALIZED"
    WAIT = "WAIT"
    RISK_REJECTED = "RISK_REJECTED"
    ELIGIBLE_NO_ORDER = "ELIGIBLE_NO_ORDER"
    VIRTUAL_CLOSE = "VIRTUAL_CLOSE"
    SAFETY_HOLD = "SAFETY_HOLD"


@dataclass(frozen=True, slots=True)
class ShadowSessionContext:
    session_id: str
    dataset_fingerprint: str
    code_commit: str
    config_fingerprint: str

    def __post_init__(self) -> None:
        values = (
            self.session_id,
            self.dataset_fingerprint,
            self.code_commit,
            self.config_fingerprint,
        )
        if any(not value.strip() for value in values):
            raise ValueError("shadow session requires complete fingerprints")


@dataclass(frozen=True, slots=True)
class ShadowAuditRecord:
    observation_id: str
    session_id: str
    decision_timestamp_utc: datetime
    action: str
    status: ShadowStatus
    selected_engine_id: str | None
    proposal_keys: tuple[str, ...]
    risk_reasons: tuple[str, ...]
    reason_codes: tuple[str, ...]
    dataset_fingerprint: str
    code_commit: str
    config_fingerprint: str
    risk_state_sha256: str | None

    def __post_init__(self) -> None:
        if not self.observation_id.strip() or not self.session_id.strip():
            raise ValueError("shadow audit identifiers must be non-empty")
        _utc(self.decision_timestamp_utc, "shadow decision timestamp")
        if not self.action.strip() or not self.reason_codes:
            raise ValueError("shadow audit requires action and reason codes")
        fingerprints = (
            self.dataset_fingerprint,
            self.code_commit,
            self.config_fingerprint,
        )
        if any(not value.strip() for value in fingerprints):
            raise ValueError("shadow audit requires complete fingerprints")
        if self.risk_state_sha256 is not None and len(self.risk_state_sha256) != 64:
            raise ValueError("shadow risk-state checksum must be SHA-256")


class ShadowAuditError(RuntimeError):
    """Raised when the append-only shadow audit cannot be trusted."""


class ShadowAuditJournal:
    """Single-writer fsynced JSONL journal with a SHA-256 hash chain."""

    def __init__(self, path: Path) -> None:
        self.path = Path(path)
        self._lock = threading.Lock()
        verified = self.verify()
        self._observation_ids = {record.observation_id for record in verified}
        self._last_hash = self._read_last_hash()

    def append(self, record: ShadowAuditRecord) -> str:
        with self._lock:
            if record.observation_id in self._observation_ids:
                raise ShadowAuditError(
                    f"duplicate shadow observation id: {record.observation_id}"
                )
            payload = _record_to_dict(record)
            chained = {"previous_sha256": self._last_hash, "record": payload}
            checksum = _digest(chained)
            envelope = {**chained, "sha256": checksum}
            encoded = (
                json.dumps(envelope, sort_keys=True, separators=(",", ":")) + "\n"
            ).encode()
            self.path.parent.mkdir(parents=True, exist_ok=True)
            descriptor = os.open(
                self.path,
                os.O_APPEND | os.O_CREAT | os.O_WRONLY,
                0o640,
            )
            try:
                written = os.write(descriptor, encoded)
                if written != len(encoded):
                    raise ShadowAuditError("short write to shadow audit journal")
                os.fsync(descriptor)
            finally:
                os.close(descriptor)
            self._last_hash = checksum
            self._observation_ids.add(record.observation_id)
            return checksum

    def ensure_available(self, observation_id: str) -> None:
        if not observation_id.strip():
            raise ValueError("shadow observation id must be non-empty")
        if observation_id in self._observation_ids:
            raise ShadowAuditError(f"duplicate shadow observation id: {observation_id}")

    def find(self, observation_id: str) -> ShadowAuditRecord | None:
        return next(
            (record for record in self.verify() if record.observation_id == observation_id),
            None,
        )

    def verify(self) -> tuple[ShadowAuditRecord, ...]:
        if not self.path.exists():
            return ()
        previous: str | None = None
        records: list[ShadowAuditRecord] = []
        seen: set[str] = set()
        try:
            lines = self.path.read_text(encoding="utf-8").splitlines()
        except UnicodeDecodeError as exc:
            raise ShadowAuditError("shadow audit is not valid UTF-8") from exc
        for line_number, line in enumerate(lines, start=1):
            try:
                envelope = json.loads(line)
                if not isinstance(envelope, dict):
                    raise TypeError("envelope is not an object")
                actual_previous = envelope["previous_sha256"]
                checksum = envelope["sha256"]
                raw_record = envelope["record"]
                if actual_previous != previous:
                    raise ValueError("hash-chain predecessor mismatch")
                if not isinstance(checksum, str) or len(checksum) != 64:
                    raise ValueError("invalid checksum")
                chained = {
                    "previous_sha256": actual_previous,
                    "record": raw_record,
                }
                if not hmac.compare_digest(checksum, _digest(chained)):
                    raise ValueError("record checksum mismatch")
                record = _record_from_dict(raw_record)
                if record.observation_id in seen:
                    raise ValueError("duplicate observation id")
            except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
                raise ShadowAuditError(
                    f"invalid shadow audit at line {line_number}"
                ) from exc
            records.append(record)
            seen.add(record.observation_id)
            previous = checksum
        return tuple(records)

    def _read_last_hash(self) -> str | None:
        if not self.path.exists():
            return None
        lines = self.path.read_text(encoding="utf-8").splitlines()
        if not lines:
            return None
        value = json.loads(lines[-1])["sha256"]
        return str(value)

    @property
    def latest_risk_state_sha256(self) -> str | None:
        records = self.verify()
        return next(
            (
                record.risk_state_sha256
                for record in reversed(records)
                if record.risk_state_sha256 is not None
            ),
            None,
        )


class ShadowRuntime:
    """Observe Meta decisions and maintain a virtual portfolio; submit nothing."""

    def __init__(
        self,
        *,
        trading_mode: TradingMode,
        context: ShadowSessionContext,
        risk_engine: PortfolioRiskEngine,
        risk_store: PortfolioRiskStateStore,
        journal: ShadowAuditJournal,
    ) -> None:
        if trading_mode is not TradingMode.SHADOW:
            raise ValueError("ShadowRuntime requires TradingMode.SHADOW")
        self.context = context
        self.risk_engine = risk_engine
        self.risk_store = risk_store
        self.journal = journal

    @classmethod
    def initialize_new(
        cls,
        *,
        trading_mode: TradingMode,
        context: ShadowSessionContext,
        risk_engine: PortfolioRiskEngine,
        risk_store: PortfolioRiskStateStore,
        journal: ShadowAuditJournal,
        initialized_at_utc: datetime,
    ) -> ShadowRuntime:
        if trading_mode is not TradingMode.SHADOW:
            raise ValueError("ShadowRuntime requires TradingMode.SHADOW")
        if risk_store.load() is not None:
            raise ValueError("cannot initialize shadow runtime over existing risk state")
        if journal.verify():
            raise ValueError("cannot initialize shadow runtime over existing audit records")
        checksum = risk_store.save(
            risk_engine.snapshot(), saved_at_utc=initialized_at_utc
        )
        runtime = cls(
            trading_mode=trading_mode,
            context=context,
            risk_engine=risk_engine,
            risk_store=risk_store,
            journal=journal,
        )
        runtime._record(
            observation_id=f"{context.session_id}:initialize",
            decision_timestamp_utc=initialized_at_utc,
            action="INITIALIZE",
            status=ShadowStatus.INITIALIZED,
            selected_engine_id=None,
            proposal_keys=(),
            risk_reasons=(),
            reason_codes=("SHADOW_SESSION_INITIALIZED",),
            risk_state_sha256=checksum,
        )
        return runtime

    @classmethod
    def resume(
        cls,
        *,
        trading_mode: TradingMode,
        context: ShadowSessionContext,
        risk_store: PortfolioRiskStateStore,
        journal: ShadowAuditJournal,
        risk_config: PortfolioRiskConfig,
    ) -> ShadowRuntime:
        snapshot = risk_store.load_required()
        records = journal.verify()
        if not records:
            raise ShadowAuditError("shadow audit is absent for persisted risk state")
        if any(
            record.session_id != context.session_id
            or record.dataset_fingerprint != context.dataset_fingerprint
            or record.code_commit != context.code_commit
            or record.config_fingerprint != context.config_fingerprint
            for record in records
        ):
            raise ShadowAuditError("shadow context does not match the existing audit")
        journal_checksum = journal.latest_risk_state_sha256
        store_checksum = risk_store.checksum()
        if journal_checksum is not None and journal_checksum != store_checksum:
            raise ShadowAuditError("shadow audit and risk state are not reconciled")
        engine = PortfolioRiskEngine.from_snapshot(snapshot, risk_config)
        return cls(
            trading_mode=trading_mode,
            context=context,
            risk_engine=engine,
            risk_store=risk_store,
            journal=journal,
        )

    def observe(
        self,
        meta: MetaDecision,
        *,
        observation_id: str,
        proposals: tuple[PortfolioEntryProposal, ...],
        equity: float,
    ) -> ShadowAuditRecord:
        self.journal.ensure_available(observation_id)
        if meta.action == SetupAction.WAIT:
            if proposals:
                raise ValueError("WAIT shadow observation cannot carry proposals")
            return self._record(
                observation_id=observation_id,
                decision_timestamp_utc=meta.decision_timestamp_utc,
                action=meta.action.value,
                status=ShadowStatus.WAIT,
                selected_engine_id=None,
                proposal_keys=(),
                risk_reasons=(),
                reason_codes=meta.reason_codes,
                risk_state_sha256=None,
            )
        self._validate_actionable(meta, proposals)
        staged = PortfolioRiskEngine.from_snapshot(
            self.risk_engine.snapshot(), self.risk_engine.config
        )
        decisions: list[PortfolioRiskDecision] = []
        for proposal in proposals:
            decision = staged.evaluate_entry(proposal, equity=equity)
            decisions.append(decision)
            if not decision.approved:
                return self._record(
                    observation_id=observation_id,
                    decision_timestamp_utc=meta.decision_timestamp_utc,
                    action=meta.action.value,
                    status=ShadowStatus.RISK_REJECTED,
                    selected_engine_id=meta.selected_engine_id,
                    proposal_keys=tuple(item.key for item in proposals),
                    risk_reasons=tuple(item.reason for item in decisions),
                    reason_codes=("PORTFOLIO_RISK_REJECTED", decision.reason),
                    risk_state_sha256=None,
                )
            staged.record_open(proposal, decision)
        if meta.action == SetupAction.ARBITRAGE and any(
            not math.isclose(
                abs(decision.approved_signed_notional),
                abs(proposal.signed_notional),
                rel_tol=1e-12,
                abs_tol=1e-12,
            )
            for proposal, decision in zip(proposals, decisions, strict=True)
        ):
            return self._record(
                observation_id=observation_id,
                decision_timestamp_utc=meta.decision_timestamp_utc,
                action=meta.action.value,
                status=ShadowStatus.RISK_REJECTED,
                selected_engine_id=meta.selected_engine_id,
                proposal_keys=tuple(item.key for item in proposals),
                risk_reasons=tuple(item.reason for item in decisions),
                reason_codes=("ARBITRAGE_LEG_CAPACITY_MISMATCH",),
                risk_state_sha256=None,
            )
        state_checksum = self.risk_store.save(
            staged.snapshot(), saved_at_utc=meta.decision_timestamp_utc
        )
        self.risk_engine = staged
        return self._record(
            observation_id=observation_id,
            decision_timestamp_utc=meta.decision_timestamp_utc,
            action=meta.action.value,
            status=ShadowStatus.ELIGIBLE_NO_ORDER,
            selected_engine_id=meta.selected_engine_id,
            proposal_keys=tuple(item.key for item in proposals),
            risk_reasons=tuple(item.reason for item in decisions),
            reason_codes=("SHADOW_ONLY_NO_ORDER_SUBMISSION",),
            risk_state_sha256=state_checksum,
        )

    def close_virtual(
        self,
        *,
        observation_id: str,
        realized_pnl_by_key: tuple[tuple[str, float], ...],
        closed_at_utc: datetime,
    ) -> ShadowAuditRecord:
        self.journal.ensure_available(observation_id)
        closed_at = _utc(closed_at_utc, "shadow close timestamp")
        keys = [key for key, _ in realized_pnl_by_key]
        if not keys or len(set(keys)) != len(keys):
            raise ValueError("shadow close requires unique position keys")
        staged = PortfolioRiskEngine.from_snapshot(
            self.risk_engine.snapshot(), self.risk_engine.config
        )
        for key, realized_pnl in realized_pnl_by_key:
            staged.record_close(key, realized_pnl=realized_pnl, closed_at_utc=closed_at)
        state_checksum = self.risk_store.save(staged.snapshot(), saved_at_utc=closed_at)
        self.risk_engine = staged
        return self._record(
            observation_id=observation_id,
            decision_timestamp_utc=closed_at,
            action="CLOSE",
            status=ShadowStatus.VIRTUAL_CLOSE,
            selected_engine_id=None,
            proposal_keys=tuple(keys),
            risk_reasons=(),
            reason_codes=("VIRTUAL_POSITION_CLOSED",),
            risk_state_sha256=state_checksum,
        )

    def activate_safety_hold(
        self,
        *,
        observation_id: str,
        reason: str,
        activated_at_utc: datetime,
    ) -> ShadowAuditRecord:
        self.journal.ensure_available(observation_id)
        activated_at = _utc(activated_at_utc, "shadow safety-hold timestamp")
        if not reason.strip():
            raise ValueError("shadow safety hold requires a reason")
        staged = PortfolioRiskEngine.from_snapshot(
            self.risk_engine.snapshot(), self.risk_engine.config
        )
        staged.activate_kill_switch(reason)
        state_checksum = self.risk_store.save(
            staged.snapshot(), saved_at_utc=activated_at
        )
        self.risk_engine = staged
        return self._record(
            observation_id=observation_id,
            decision_timestamp_utc=activated_at,
            action="SAFETY_HOLD",
            status=ShadowStatus.SAFETY_HOLD,
            selected_engine_id=None,
            proposal_keys=(),
            risk_reasons=(reason,),
            reason_codes=("SHADOW_EVENT_LOOP_FAILURE_THRESHOLD",),
            risk_state_sha256=state_checksum,
        )

    def _validate_actionable(
        self,
        meta: MetaDecision,
        proposals: tuple[PortfolioEntryProposal, ...],
    ) -> None:
        setup = meta.selected_setup
        if setup is None or meta.selected_engine_id is None:
            raise ValueError("actionable shadow decision must select a setup")
        if not proposals or len(proposals) != len(setup.legs):
            raise ValueError("shadow proposals must map one-to-one to setup legs")
        if len({proposal.key for proposal in proposals}) != len(proposals):
            raise ValueError("shadow proposal keys must be unique")
        expected = Counter(
            (leg.symbol, leg.venue.lower(), 1 if leg.side == LegSide.BUY else -1)
            for leg in setup.legs
        )
        actual = Counter(
            (
                proposal.symbol,
                proposal.venue.lower(),
                1 if proposal.signed_notional > 0 else -1,
            )
            for proposal in proposals
        )
        if actual != expected:
            raise ValueError("shadow proposals do not match selected setup legs")
        decision_time = meta.decision_timestamp_utc.astimezone(UTC)
        if any(
            proposal.proposed_at_utc.astimezone(UTC) != decision_time
            for proposal in proposals
        ):
            raise ValueError("shadow proposals must share the Meta decision timestamp")
        if any(abs(proposal.signed_notional) > meta.allocated_notional for proposal in proposals):
            raise ValueError("shadow proposal exceeds Meta allocation")
        if meta.action != SetupAction.ARBITRAGE and sum(
            abs(proposal.signed_notional) for proposal in proposals
        ) > meta.allocated_notional:
            raise ValueError("directional shadow proposals exceed total Meta allocation")
        if meta.action == SetupAction.ARBITRAGE:
            notionals = [abs(proposal.signed_notional) for proposal in proposals]
            if not all(
                math.isclose(value, notionals[0], rel_tol=1e-12, abs_tol=1e-12)
                for value in notionals[1:]
            ):
                raise ValueError("shadow arbitrage legs must start balanced")

    def _record(
        self,
        *,
        observation_id: str,
        decision_timestamp_utc: datetime,
        action: str,
        status: ShadowStatus,
        selected_engine_id: str | None,
        proposal_keys: tuple[str, ...],
        risk_reasons: tuple[str, ...],
        reason_codes: tuple[str, ...],
        risk_state_sha256: str | None,
    ) -> ShadowAuditRecord:
        record = ShadowAuditRecord(
            observation_id=observation_id,
            session_id=self.context.session_id,
            decision_timestamp_utc=decision_timestamp_utc,
            action=action,
            status=status,
            selected_engine_id=selected_engine_id,
            proposal_keys=proposal_keys,
            risk_reasons=risk_reasons,
            reason_codes=reason_codes,
            dataset_fingerprint=self.context.dataset_fingerprint,
            code_commit=self.context.code_commit,
            config_fingerprint=self.context.config_fingerprint,
            risk_state_sha256=risk_state_sha256,
        )
        self.journal.append(record)
        return record


def _record_to_dict(record: ShadowAuditRecord) -> dict[str, Any]:
    value = asdict(record)
    value["decision_timestamp_utc"] = record.decision_timestamp_utc.astimezone(
        UTC
    ).isoformat()
    value["status"] = record.status.value
    return value


def _record_from_dict(value: Any) -> ShadowAuditRecord:
    if not isinstance(value, dict):
        raise TypeError("shadow record must be an object")
    return ShadowAuditRecord(
        observation_id=_string(value, "observation_id"),
        session_id=_string(value, "session_id"),
        decision_timestamp_utc=datetime.fromisoformat(
            _string(value, "decision_timestamp_utc").replace("Z", "+00:00")
        ),
        action=_string(value, "action"),
        status=ShadowStatus(_string(value, "status")),
        selected_engine_id=_optional_string(value, "selected_engine_id"),
        proposal_keys=_string_tuple(value, "proposal_keys"),
        risk_reasons=_string_tuple(value, "risk_reasons"),
        reason_codes=_string_tuple(value, "reason_codes"),
        dataset_fingerprint=_string(value, "dataset_fingerprint"),
        code_commit=_string(value, "code_commit"),
        config_fingerprint=_string(value, "config_fingerprint"),
        risk_state_sha256=_optional_string(value, "risk_state_sha256"),
    )


def _string(value: dict[str, Any], key: str) -> str:
    item = value[key]
    if not isinstance(item, str):
        raise TypeError(f"{key} must be a string")
    return item


def _optional_string(value: dict[str, Any], key: str) -> str | None:
    item = value[key]
    if item is not None and not isinstance(item, str):
        raise TypeError(f"{key} must be a string or null")
    return item


def _string_tuple(value: dict[str, Any], key: str) -> tuple[str, ...]:
    item = value[key]
    if not isinstance(item, list) or any(not isinstance(element, str) for element in item):
        raise TypeError(f"{key} must be a string list")
    return tuple(item)


def _digest(value: dict[str, Any]) -> str:
    canonical = json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(canonical).hexdigest()


def _utc(value: datetime, name: str) -> datetime:
    if value.tzinfo is None:
        raise ValueError(f"{name} must be timezone-aware")
    return value.astimezone(UTC)
