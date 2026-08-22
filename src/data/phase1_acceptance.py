"""Fail-closed Phase 1 acceptance gate over operational evidence artifacts."""

from __future__ import annotations

import hashlib
import json
import os
import re
import uuid
from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

EXPECTED_COLLECTORS = ("btcusdt", "ethusdt", "solusdt")
EXPECTED_SYMBOLS = ("BTCUSDT", "ETHUSDT", "SOLUSDT")
REQUIRED_CHANNELS = ("orderbook", "trades", "ticker", "liquidations")
REQUIRED_DRILLS = (
    "graceful_sigterm",
    "process_restart",
    "vps_reboot",
    "disk_backlog",
    "storage_restore",
)
MINIMUM_SOAK_SECS = 7 * 24 * 60 * 60
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_GIT_SHA = re.compile(r"^[0-9a-f]{40}$")


@dataclass(frozen=True, slots=True)
class AcceptanceCheck:
    name: str
    passed: bool
    detail: str


@dataclass(frozen=True, slots=True)
class PhaseOneAcceptanceReport:
    schema_version: int
    qualified: bool
    source_commit: str
    input_sha256: dict[str, str]
    checks: tuple[AcceptanceCheck, ...]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def evaluate_phase1_acceptance(
    *,
    soak_report: Mapping[str, Any],
    replay_report: Mapping[str, Any],
    operational_evidence: Mapping[str, Any],
    expected_commit: str,
) -> PhaseOneAcceptanceReport:
    """Evaluate every Phase 1 exit artifact without silently assuming evidence."""

    checks: list[AcceptanceCheck] = []

    def check(name: str, passed: bool, detail: str) -> None:
        checks.append(AcceptanceCheck(name=name, passed=bool(passed), detail=detail))

    commit = str(operational_evidence.get("source_commit", ""))
    check(
        "evidence_schema_versions",
        soak_report.get("schema_version") == 1
        and operational_evidence.get("schema_version") == 1,
        (
            f"soak={soak_report.get('schema_version')}; "
            f"operational={operational_evidence.get('schema_version')}"
        ),
    )
    check(
        "source_commit",
        _valid_git_sha(expected_commit) and commit == expected_commit,
        f"evidence={commit or '<missing>'}; expected={expected_commit}",
    )

    required_duration = _number(soak_report.get("required_duration_secs"))
    start_ns = _integer(soak_report.get("start_ts_ns"))
    end_ns = _integer(soak_report.get("end_ts_ns"))
    observed_duration = (end_ns - start_ns) / 1_000_000_000 if end_ns > start_ns else 0
    check(
        "seven_day_soak_window",
        bool(soak_report.get("qualified"))
        and required_duration >= MINIMUM_SOAK_SECS
        and observed_duration >= MINIMUM_SOAK_SECS,
        f"required={required_duration:.0f}s; observed={observed_duration:.0f}s",
    )

    collectors = _mapping(soak_report.get("collectors"))
    check(
        "collector_set",
        set(collectors) == set(EXPECTED_COLLECTORS),
        f"observed={sorted(collectors)}; expected={list(EXPECTED_COLLECTORS)}",
    )
    incident_requirements: Counter[tuple[str, str]] = Counter()
    collectors_clean = True
    for collector_id in EXPECTED_COLLECTORS:
        result = _mapping(collectors.get(collector_id))
        dropped = _integer(result.get("dropped_events_observed"))
        uncertainties = _integer(result.get("sequence_uncertainties_observed"))
        reconnects = _integer(result.get("reconnects_observed"))
        clean = (
            bool(result.get("qualified"))
            and _integer(result.get("sample_count")) > 0
            and dropped == 0
            and not _sequence(result.get("errors"))
        )
        collectors_clean = collectors_clean and clean
        incident_requirements[(collector_id, "sequence_uncertainty")] += uncertainties
        incident_requirements[(collector_id, "reconnect")] += reconnects
    check(
        "collector_health_evidence",
        collectors_clean,
        "all collectors qualified with samples, zero drops, and zero unresolved audit errors",
    )

    raw_event_count = _integer(replay_report.get("raw_event_count"))
    channel_counts = _mapping(replay_report.get("channel_counts"))
    missing_channels = [
        channel for channel in REQUIRED_CHANNELS if _integer(channel_counts.get(channel)) <= 0
    ]
    check(
        "replay_channels",
        raw_event_count > 0 and not missing_channels,
        f"raw_events={raw_event_count}; missing_nonempty_channels={missing_channels}",
    )
    books = _mapping(replay_report.get("orderbooks"))
    tickers = _mapping(replay_report.get("ticker_checksums"))
    replay_checksum = str(replay_report.get("replay_checksum", ""))
    replay_complete = (
        set(books) == set(EXPECTED_SYMBOLS)
        and set(tickers) == set(EXPECTED_SYMBOLS)
        and _valid_sha256(replay_checksum)
    )
    for symbol in EXPECTED_SYMBOLS:
        book = _mapping(books.get(symbol))
        replay_complete = replay_complete and (
            _integer(book.get("bid_levels")) > 0
            and _integer(book.get("ask_levels")) > 0
            and _valid_sha256(book.get("checksum"))
        )
    check(
        "deterministic_replay",
        replay_complete,
        f"books={sorted(books)}; tickers={sorted(tickers)}; checksum={replay_checksum}",
    )

    alert_delivery = _mapping(operational_evidence.get("alert_delivery"))
    alert_ok = (
        alert_delivery.get("passed") is True
        and _valid_timestamp(alert_delivery.get("tested_at_utc"))
        and _valid_sha256(alert_delivery.get("journal_event_id"))
        and _meaningful(alert_delivery.get("durable_journal_evidence"))
        and _meaningful(alert_delivery.get("external_delivery_evidence"))
    )
    check(
        "off_host_alert_delivery",
        alert_ok,
        "requires timestamp, durable journal event ID, and external-channel receipt",
    )

    drills = _mapping(operational_evidence.get("drills"))
    failed_drills = [
        name for name in REQUIRED_DRILLS if not _valid_drill(_mapping(drills.get(name)))
    ]
    check(
        "recovery_drills",
        not failed_drills,
        f"missing_or_failed={failed_drills}",
    )

    incidents = _sequence(operational_evidence.get("incident_reconciliations"))
    valid_incidents = [_mapping(item) for item in incidents]
    incident_ids = [str(item.get("incident_id", "")) for item in valid_incidents]
    duplicate_ids = sorted(
        incident_id
        for incident_id, count in Counter(incident_ids).items()
        if incident_id and count > 1
    )
    malformed = [
        str(item.get("incident_id", "<missing>"))
        for item in valid_incidents
        if not _valid_incident(item)
    ]
    observed_incidents: Counter[tuple[str, str]] = Counter(
        (str(item.get("collector_id")), str(item.get("incident_type")))
        for item in valid_incidents
        if _valid_incident(item)
    )
    under_reconciled = {
        f"{collector_id}:{kind}": required - observed_incidents[(collector_id, kind)]
        for (collector_id, kind), required in incident_requirements.items()
        if observed_incidents[(collector_id, kind)] < required
    }
    check(
        "incident_reconciliation",
        not malformed and not duplicate_ids and not under_reconciled,
        (
            f"malformed={malformed}; duplicate_ids={duplicate_ids}; "
            f"missing_reconciliations={under_reconciled}"
        ),
    )

    approval = _mapping(operational_evidence.get("operator_approval"))
    approval_ok = (
        approval.get("approved") is True
        and _meaningful(approval.get("operator"))
        and _valid_timestamp(approval.get("approved_at_utc"))
        and _meaningful(approval.get("evidence_bundle_reference"))
    )
    check(
        "operator_approval",
        approval_ok,
        "requires explicit named approval and immutable evidence-bundle reference",
    )

    inputs = {
        "soak_report": _document_sha256(soak_report),
        "replay_report": _document_sha256(replay_report),
        "operational_evidence": _document_sha256(operational_evidence),
    }
    return PhaseOneAcceptanceReport(
        schema_version=1,
        qualified=all(item.passed for item in checks),
        source_commit=expected_commit,
        input_sha256=inputs,
        checks=tuple(checks),
    )


def write_acceptance_report(path: Path, report: PhaseOneAcceptanceReport) -> None:
    value = json.dumps(report.to_dict(), sort_keys=True, indent=2) + "\n"
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    try:
        with temp_path.open("w", encoding="utf-8", newline="\n") as handle:
            handle.write(value)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_path, path)
    finally:
        temp_path.unlink(missing_ok=True)


def _valid_drill(drill: Mapping[str, Any]) -> bool:
    return (
        drill.get("passed") is True
        and _valid_timestamp(drill.get("tested_at_utc"))
        and _meaningful(drill.get("operator"))
        and _meaningful(drill.get("evidence_reference"))
        and _valid_sha256(drill.get("replay_checksum"))
    )


def _valid_incident(incident: Mapping[str, Any]) -> bool:
    return (
        _meaningful(incident.get("incident_id"))
        and incident.get("collector_id") in EXPECTED_COLLECTORS
        and incident.get("incident_type") in {"reconnect", "sequence_uncertainty"}
        and incident.get("reconciled") is True
        and _valid_timestamp(incident.get("occurred_at_utc"))
        and _meaningful(incident.get("evidence_reference"))
        and _meaningful(incident.get("next_snapshot_connection_id"))
        and _valid_sha256(incident.get("replay_checksum"))
    )


def _valid_timestamp(value: Any) -> bool:
    if not isinstance(value, str) or not value:
        return False
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return False
    return parsed.tzinfo is not None and parsed.year >= 2024


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _sequence(value: Any) -> Sequence[Any]:
    return value if isinstance(value, Sequence) and not isinstance(value, (str, bytes)) else ()


def _integer(value: Any) -> int:
    return int(value) if isinstance(value, int) and not isinstance(value, bool) else 0


def _number(value: Any) -> float:
    return float(value) if isinstance(value, (int, float)) and not isinstance(value, bool) else 0.0


def _meaningful(value: Any) -> bool:
    if not isinstance(value, str):
        return False
    normalized = value.strip().lower()
    return bool(normalized) and normalized not in {"replace-me", "todo", "tbd"}


def _valid_sha256(value: Any) -> bool:
    normalized = str(value)
    return bool(_SHA256.fullmatch(normalized)) and set(normalized) != {"0"}


def _valid_git_sha(value: Any) -> bool:
    normalized = str(value)
    return bool(_GIT_SHA.fullmatch(normalized)) and set(normalized) != {"0"}


def _document_sha256(value: Mapping[str, Any]) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()
