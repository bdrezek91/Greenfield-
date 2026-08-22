"""End-to-end alert evidence must correlate local and external delivery."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.data.phase1_alert_delivery import (
    evaluate_phase1_alert_delivery,
    load_alert_journal,
    write_alert_delivery_report,
)

EVENT_ID = "a" * 64
COMMIT = "b" * 40
SESSION = "phase1-session"
RECEIVED_NS = 1_800_000_000_000_000_000


def _journal() -> list[dict]:
    payload = {
        "status": "firing",
        "alerts": [
            {
                "status": "firing",
                "labels": {
                    "alertname": "GreenfieldDeliveryTest",
                    "component": "test",
                    "owner": "operator-a",
                    "session_id": SESSION,
                    "source_commit": COMMIT,
                },
            }
        ],
    }
    return [
        {
            "schema_version": 1,
            "record_type": "alertmanager_receipt",
            "event_id": EVENT_ID,
            "received_at_ns": RECEIVED_NS,
            "payload": payload,
        },
        {
            "schema_version": 1,
            "record_type": "forward_success",
            "event_id": EVENT_ID,
            "received_at_ns": RECEIVED_NS + 1_000_000_000,
        },
    ]


def _external() -> dict:
    return {
        "schema_version": 1,
        "event_id": EVENT_ID,
        "delivery_status": "delivered",
        "received_at_utc": "2027-01-15T08:00:02+00:00",
        "receipt_id": "external-message-123",
        "destination": "operator-alert-channel",
    }


def _evaluate():
    return evaluate_phase1_alert_delivery(
        journal_records=_journal(),
        external_receipt=_external(),
        event_id=EVENT_ID,
        session_id=SESSION,
        source_commit=COMMIT,
        operator="operator-a",
    )


def test_correlated_journal_and_external_receipt_qualify(tmp_path: Path) -> None:
    report = _evaluate()
    assert report.qualified
    output = tmp_path / "alert-delivery.json"
    write_alert_delivery_report(output, report)
    assert '"qualified": true' in output.read_text(encoding="utf-8")
    with pytest.raises(FileExistsError, match="will not be overwritten"):
        write_alert_delivery_report(output, report)


def test_wrong_event_identity_or_missing_forward_success_fails() -> None:
    receipt = _external()
    receipt["event_id"] = "c" * 64
    wrong_event = evaluate_phase1_alert_delivery(
        journal_records=_journal(),
        external_receipt=receipt,
        event_id=EVENT_ID,
        session_id=SESSION,
        source_commit=COMMIT,
        operator="operator-a",
    )
    assert not wrong_event.qualified

    missing_success = evaluate_phase1_alert_delivery(
        journal_records=_journal()[:1],
        external_receipt=_external(),
        event_id=EVENT_ID,
        session_id=SESSION,
        source_commit=COMMIT,
        operator="operator-a",
    )
    assert not missing_success.qualified


def test_cross_session_or_late_receipt_fails() -> None:
    receipt = _external()
    receipt["received_at_utc"] = "2027-01-15T10:00:02+00:00"
    report = evaluate_phase1_alert_delivery(
        journal_records=_journal(),
        external_receipt=receipt,
        event_id=EVENT_ID,
        session_id="other-session",
        source_commit=COMMIT,
        operator="operator-a",
    )
    failed = {item.name for item in report.checks if not item.passed}
    assert {"synthetic_alert_identity", "bounded_external_delivery_delay"} <= failed


def test_journal_loader_rejects_malformed_lines(tmp_path: Path) -> None:
    path = tmp_path / "journal.jsonl"
    path.write_text("{}\nnot-json\n", encoding="utf-8")
    with pytest.raises(ValueError, match="line 2"):
        load_alert_journal(path)

    path.write_text("\n", encoding="utf-8")
    with pytest.raises(ValueError, match="empty"):
        load_alert_journal(path)

    path.write_text("\n".join(json.dumps(item) for item in _journal()), encoding="utf-8")
    assert len(load_alert_journal(path)) == 2
