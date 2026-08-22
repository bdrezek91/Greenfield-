"""Machine-verifiable end-to-end alert delivery evidence for Phase 1."""

from __future__ import annotations

import json
import os
import re
import uuid
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_GIT_SHA = re.compile(r"^[0-9a-f]{40}$")
MAX_EXTERNAL_DELAY_SECS = 60 * 60


@dataclass(frozen=True, slots=True)
class AlertDeliveryCheck:
    name: str
    passed: bool
    detail: str


@dataclass(frozen=True, slots=True)
class PhaseOneAlertDeliveryReport:
    schema_version: int
    qualified: bool
    session_id: str
    source_commit: str
    operator: str
    event_id: str
    completed_at_utc: str
    checks: tuple[AlertDeliveryCheck, ...]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def evaluate_phase1_alert_delivery(
    *,
    journal_records: Sequence[Mapping[str, Any]],
    external_receipt: Mapping[str, Any],
    event_id: str,
    session_id: str,
    source_commit: str,
    operator: str,
) -> PhaseOneAlertDeliveryReport:
    checks: list[AlertDeliveryCheck] = []

    def check(name: str, passed: bool, detail: str) -> None:
        checks.append(AlertDeliveryCheck(name, bool(passed), detail))

    check("event_id", _valid_sha256(event_id), f"event_id={event_id or '<missing>'}")
    check(
        "identity",
        _meaningful(session_id)
        and _valid_git_sha(source_commit)
        and _meaningful(operator),
        f"session={session_id}; commit={source_commit}; operator={operator}",
    )

    matching = [item for item in journal_records if item.get("event_id") == event_id]
    receipts = [
        item for item in matching if item.get("record_type") == "alertmanager_receipt"
    ]
    successes = [item for item in matching if item.get("record_type") == "forward_success"]
    receipt_record = receipts[-1] if receipts else {}
    receipt_ns = _positive_integer(receipt_record.get("received_at_ns"))
    success_ns = max(
        (_positive_integer(item.get("received_at_ns")) for item in successes),
        default=0,
    )
    check(
        "durable_journal_chain",
        bool(receipts) and bool(successes) and receipt_ns > 0 and success_ns >= receipt_ns,
        (
            f"matching={len(matching)}; receipts={len(receipts)}; "
            f"successes={len(successes)}"
        ),
    )

    payload = _mapping(receipt_record.get("payload"))
    alert_items = _sequence(payload.get("alerts"))
    synthetic = [
        _mapping(item)
        for item in alert_items
        if _mapping(_mapping(item).get("labels")).get("alertname")
        == "GreenfieldDeliveryTest"
    ]
    labels = _mapping(synthetic[0].get("labels")) if len(synthetic) == 1 else {}
    identity_match = (
        len(synthetic) == 1
        and labels.get("owner") == operator
        and labels.get("session_id") == session_id
        and labels.get("source_commit") == source_commit
        and labels.get("component") == "test"
    )
    check(
        "synthetic_alert_identity",
        identity_match,
        f"matching_test_alerts={len(synthetic)}; labels={dict(labels)}",
    )

    external_event_id = external_receipt.get("event_id")
    completed_at = str(external_receipt.get("received_at_utc", ""))
    completed_ns = _timestamp_ns_or_zero(completed_at)
    external_ok = (
        external_receipt.get("schema_version") == 1
        and external_receipt.get("delivery_status") == "delivered"
        and external_event_id == event_id
        and _meaningful(external_receipt.get("receipt_id"))
        and _meaningful(external_receipt.get("destination"))
        and completed_ns > 0
    )
    check(
        "external_receipt",
        external_ok,
        (
            f"event_id={external_event_id}; status="
            f"{external_receipt.get('delivery_status')}"
        ),
    )
    # The external endpoint observes the request before the local sender can
    # append ``forward_success``. Compare with the durable pre-send receipt and
    # tolerate at most one minute of cross-host clock skew.
    delivery_delay_ns = completed_ns - receipt_ns
    timely = (
        external_ok
        and receipt_ns > 0
        and -60 * 1_000_000_000
        <= delivery_delay_ns
        <= MAX_EXTERNAL_DELAY_SECS * 1_000_000_000
    )
    check(
        "bounded_external_delivery_delay",
        timely,
        f"delay_secs={delivery_delay_ns / 1_000_000_000:.3f}",
    )

    return PhaseOneAlertDeliveryReport(
        schema_version=1,
        qualified=all(item.passed for item in checks),
        session_id=session_id,
        source_commit=source_commit,
        operator=operator,
        event_id=event_id,
        completed_at_utc=completed_at,
        checks=tuple(checks),
    )


def load_alert_journal(path: Path) -> tuple[Mapping[str, Any], ...]:
    records: list[Mapping[str, Any]] = []
    with Path(path).open(encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            if not line.strip():
                continue
            try:
                value = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ValueError(f"invalid journal JSON on line {line_number}") from exc
            if not isinstance(value, dict):
                raise ValueError(f"journal line {line_number} must be a JSON object")
            records.append(value)
    if not records:
        raise ValueError("alert journal is empty")
    return tuple(records)


def write_alert_delivery_report(
    path: Path, report: PhaseOneAlertDeliveryReport
) -> None:
    value = json.dumps(report.to_dict(), sort_keys=True, indent=2) + "\n"
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    try:
        with temporary.open("x", encoding="utf-8", newline="\n") as handle:
            handle.write(value)
            handle.flush()
            os.fsync(handle.fileno())
        os.link(temporary, path)
    except FileExistsError as exc:
        raise FileExistsError(
            f"alert delivery report already exists and will not be overwritten: {path}"
        ) from exc
    finally:
        temporary.unlink(missing_ok=True)


def _timestamp_ns_or_zero(value: str) -> int:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return 0
    if parsed.tzinfo is None:
        return 0
    return int(parsed.timestamp() * 1_000_000_000)


def _positive_integer(value: Any) -> int:
    return value if isinstance(value, int) and not isinstance(value, bool) and value > 0 else 0


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _sequence(value: Any) -> Sequence[Any]:
    return value if isinstance(value, Sequence) and not isinstance(value, (str, bytes)) else ()


def _meaningful(value: Any) -> bool:
    if not isinstance(value, str):
        return False
    normalized = value.strip().lower()
    return bool(normalized) and normalized not in {"replace-me", "todo", "tbd"}


def _valid_sha256(value: str) -> bool:
    return bool(_SHA256.fullmatch(value)) and set(value) != {"0"}


def _valid_git_sha(value: str) -> bool:
    return bool(_GIT_SHA.fullmatch(value)) and set(value) != {"0"}
