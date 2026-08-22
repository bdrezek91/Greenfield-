"""Phase 1 cannot pass without complete, reconciled operational evidence."""

from __future__ import annotations

from copy import deepcopy
from pathlib import Path

from src.data.phase1_acceptance import (
    REQUIRED_DRILLS,
    evaluate_phase1_acceptance,
    write_acceptance_report,
)
from src.data.phase1_evidence_bundle import REQUIRED_ARTIFACT_ROLES

SHA = "a" * 64
COMMIT = "b" * 40


def _soak(*, reconnects: int = 0, uncertainties: int = 0) -> dict:
    collectors = {}
    for collector_id in ("btcusdt", "ethusdt", "solusdt"):
        collectors[collector_id] = {
            "qualified": True,
            "sample_count": 120_961,
            "dropped_events_observed": 0,
            "sequence_uncertainties_observed": (
                uncertainties if collector_id == "btcusdt" else 0
            ),
            "reconnects_observed": reconnects if collector_id == "btcusdt" else 0,
            "errors": [],
        }
    return {
        "schema_version": 2,
        "qualified": True,
        "start_ts_ns": 1_000_000_000,
        "end_ts_ns": 604_801_000_000_000,
        "required_duration_secs": 604_800,
        "collectors": collectors,
        "session_id": "phase1-session",
        "source_commit": COMMIT,
        "session_manifest_sha256": SHA,
    }


def _replay() -> dict:
    books = {
        symbol: {"bid_levels": 50, "ask_levels": 50, "checksum": SHA}
        for symbol in ("BTCUSDT", "ETHUSDT", "SOLUSDT")
    }
    return {
        "raw_event_count": 1_000_000,
        "channel_counts": {
            "orderbook": 800_000,
            "trades": 150_000,
            "ticker": 49_000,
            "liquidations": 1_000,
        },
        "orderbooks": books,
        "ticker_checksums": {symbol: SHA for symbol in books},
        "replay_checksum": SHA,
    }


def _evidence() -> dict:
    drill = {
        "passed": True,
        "tested_at_utc": "2026-08-22T12:00:00Z",
        "operator": "operator",
        "evidence_reference": "immutable://drill",
        "evidence_sha256": SHA,
        "replay_checksum": SHA,
    }
    return {
        "schema_version": 1,
        "source_commit": COMMIT,
        "alert_delivery": {
            "passed": True,
            "tested_at_utc": "2026-08-22T12:00:00Z",
            "operator": "operator",
            "journal_event_id": SHA,
            "durable_journal_evidence": "immutable://journal",
            "external_delivery_evidence": "immutable://operator-channel",
            "evidence_reference": "immutable://alert-report",
            "evidence_sha256": SHA,
        },
        "drills": {name: deepcopy(drill) for name in REQUIRED_DRILLS},
        "incident_reconciliations": [],
        "operator_approval": {
            "approved": True,
            "operator": "operator",
            "approved_at_utc": "2026-08-22T13:00:00+00:00",
            "evidence_bundle_reference": "immutable://phase1-bundle",
            "evidence_bundle_sha256": SHA,
        },
    }


def _drill_reports(evidence: dict) -> dict[str, dict]:
    return {
        name: {
            "schema_version": 1,
            "drill_type": name,
            "qualified": True,
            "session_id": "phase1-session",
            "source_commit": COMMIT,
            "operator": drill["operator"],
            "started_at_utc": "2026-08-22T11:59:00Z",
            "completed_at_utc": drill["tested_at_utc"],
            "replay_checksum": drill["replay_checksum"],
            "checks": [{"name": "objective-proof", "passed": True, "detail": "ok"}],
        }
        for name, drill in evidence["drills"].items()
    }


def _alert_report(evidence: dict) -> dict:
    alert = evidence["alert_delivery"]
    return {
        "schema_version": 1,
        "qualified": True,
        "session_id": "phase1-session",
        "source_commit": COMMIT,
        "operator": alert["operator"],
        "event_id": alert["journal_event_id"],
        "completed_at_utc": alert["tested_at_utc"],
        "checks": [{"name": "correlated", "passed": True, "detail": "ok"}],
    }


def _incident_hashes(evidence: dict) -> dict[str, str]:
    return {
        incident["incident_id"]: SHA
        for incident in evidence["incident_reconciliations"]
    }


def _bundle_hashes(evidence: dict) -> dict[str, str]:
    values = {name: SHA for name in REQUIRED_ARTIFACT_ROLES}
    values.update(
        {
            f"incident/{incident_id}": sha256
            for incident_id, sha256 in _incident_hashes(evidence).items()
        }
    )
    return values


def _evaluate(
    *,
    soak: dict | None = None,
    replay: dict | None = None,
    evidence: dict | None = None,
    expected_commit: str = COMMIT,
    source_file_hashes: dict[str, str] | None = None,
):
    resolved_evidence = evidence or _evidence()
    bundle_hashes = _bundle_hashes(resolved_evidence)
    return evaluate_phase1_acceptance(
        soak_report=soak or _soak(),
        replay_report=replay or _replay(),
        operational_evidence=resolved_evidence,
        expected_commit=expected_commit,
        drill_reports=_drill_reports(resolved_evidence),
        drill_report_hashes={name: SHA for name in REQUIRED_DRILLS},
        evidence_bundle={
            "schema_version": 1,
            "session_id": "phase1-session",
            "source_commit": COMMIT,
            "generated_at_utc": "2026-08-22T12:30:00Z",
            "artifacts": [
                {"role": name, "sha256": SHA}
                for name in bundle_hashes
            ],
        },
        evidence_bundle_sha256=SHA,
        bundle_artifact_hashes=bundle_hashes,
        source_file_hashes=source_file_hashes
        or {"soak_report": SHA, "replay_report": SHA},
        alert_delivery_report=_alert_report(resolved_evidence),
        alert_delivery_report_sha256=SHA,
        incident_evidence_hashes=_incident_hashes(resolved_evidence),
    )


def test_complete_phase1_evidence_qualifies_and_is_hashed(tmp_path: Path) -> None:
    report = _evaluate()

    assert report.qualified
    assert len(report.input_sha256) == 5 + len(REQUIRED_DRILLS)
    assert all(len(value) == 64 for value in report.input_sha256.values())
    output = tmp_path / "acceptance.json"
    write_acceptance_report(output, report)
    assert '"qualified": true' in output.read_text(encoding="utf-8")
    assert not list(tmp_path.glob("*.tmp"))


def test_short_soak_missing_channel_and_failed_drill_fail_closed() -> None:
    soak = _soak()
    soak["required_duration_secs"] = 60
    replay = _replay()
    del replay["channel_counts"]["liquidations"]
    evidence = _evidence()
    evidence["drills"]["vps_reboot"]["passed"] = False

    report = _evaluate(soak=soak, replay=replay, evidence=evidence)

    failed = {check.name for check in report.checks if not check.passed}
    assert not report.qualified
    assert {"seven_day_soak_window", "replay_channels", "recovery_drills"} <= failed


def test_every_observed_reconnect_and_uncertainty_requires_reconciliation() -> None:
    evidence = _evidence()
    base_incident = {
        "incident_id": "INC-1",
        "collector_id": "btcusdt",
        "incident_type": "reconnect",
        "occurred_at_utc": "2026-08-22T12:00:00Z",
        "reconciled": True,
        "evidence_reference": "immutable://incident",
        "evidence_sha256": SHA,
        "next_snapshot_connection_id": "connection-2",
        "replay_checksum": SHA,
    }
    evidence["incident_reconciliations"] = [base_incident]

    incomplete = _evaluate(
        soak=_soak(reconnects=1, uncertainties=1), evidence=evidence
    )
    assert not next(
        check for check in incomplete.checks if check.name == "incident_reconciliation"
    ).passed

    uncertainty = deepcopy(base_incident)
    uncertainty.update(incident_id="INC-2", incident_type="sequence_uncertainty")
    evidence["incident_reconciliations"].append(uncertainty)
    complete = _evaluate(soak=_soak(reconnects=1, uncertainties=1), evidence=evidence)
    assert complete.qualified


def test_commit_mismatch_and_placeholder_operator_approval_fail() -> None:
    evidence = _evidence()
    evidence["operator_approval"]["approved"] = False
    report = _evaluate(evidence=evidence, expected_commit="c" * 40)
    failed = {check.name for check in report.checks if not check.passed}
    assert {"source_commit", "operator_approval"} <= failed


def test_duplicate_incident_ids_and_template_placeholders_fail() -> None:
    evidence = _evidence()
    incident = {
        "incident_id": "INC-1",
        "collector_id": "btcusdt",
        "incident_type": "reconnect",
        "occurred_at_utc": "2026-08-22T12:00:00Z",
        "reconciled": True,
        "evidence_reference": "immutable://incident",
        "evidence_sha256": SHA,
        "next_snapshot_connection_id": "connection-2",
        "replay_checksum": SHA,
    }
    evidence["incident_reconciliations"] = [incident, deepcopy(incident)]
    evidence["drills"]["storage_restore"]["operator"] = "replace-me"

    report = _evaluate(soak=_soak(reconnects=1), evidence=evidence)

    failed = {check.name for check in report.checks if not check.passed}
    assert {"incident_reconciliation", "recovery_drills"} <= failed


def test_tampered_or_cross_session_drill_report_fails_closed() -> None:
    evidence = _evidence()
    reports = _drill_reports(evidence)
    reports["vps_reboot"]["session_id"] = "different-session"
    hashes = {name: SHA for name in REQUIRED_DRILLS}
    hashes["storage_restore"] = "c" * 64

    report = evaluate_phase1_acceptance(
        soak_report=_soak(),
        replay_report=_replay(),
        operational_evidence=evidence,
        expected_commit=COMMIT,
        drill_reports=reports,
        drill_report_hashes=hashes,
        evidence_bundle={
            "schema_version": 1,
            "session_id": "phase1-session",
            "source_commit": COMMIT,
            "generated_at_utc": "2026-08-22T12:30:00Z",
            "artifacts": [
                {"role": name, "sha256": SHA}
                for name in REQUIRED_ARTIFACT_ROLES
            ],
        },
        evidence_bundle_sha256=SHA,
        bundle_artifact_hashes={name: SHA for name in REQUIRED_ARTIFACT_ROLES},
        source_file_hashes={"soak_report": SHA, "replay_report": SHA},
        alert_delivery_report=_alert_report(evidence),
        alert_delivery_report_sha256=SHA,
        incident_evidence_hashes={},
    )

    assert not report.qualified
    assert not next(
        check for check in report.checks if check.name == "recovery_drills"
    ).passed


def test_evidence_bundle_hash_or_source_substitution_fails_closed() -> None:
    evidence = _evidence()
    evidence["operator_approval"]["evidence_bundle_sha256"] = "c" * 64

    report = _evaluate(evidence=evidence)

    failed = {check.name for check in report.checks if not check.passed}
    assert "immutable_evidence_bundle" in failed

    substituted = _evaluate(
        source_file_hashes={"soak_report": "c" * 64, "replay_report": SHA}
    )
    assert not next(
        check
        for check in substituted.checks
        if check.name == "immutable_evidence_bundle"
    ).passed


def test_alert_report_must_match_operator_event_and_hash() -> None:
    evidence = _evidence()
    report = _alert_report(evidence)
    report["event_id"] = "c" * 64

    result = evaluate_phase1_acceptance(
        soak_report=_soak(),
        replay_report=_replay(),
        operational_evidence=evidence,
        expected_commit=COMMIT,
        drill_reports=_drill_reports(evidence),
        drill_report_hashes={name: SHA for name in REQUIRED_DRILLS},
        evidence_bundle={
            "schema_version": 1,
            "session_id": "phase1-session",
            "source_commit": COMMIT,
            "generated_at_utc": "2026-08-22T12:30:00Z",
            "artifacts": [
                {"role": name, "sha256": SHA}
                for name in REQUIRED_ARTIFACT_ROLES
            ],
        },
        evidence_bundle_sha256=SHA,
        bundle_artifact_hashes={name: SHA for name in REQUIRED_ARTIFACT_ROLES},
        source_file_hashes={"soak_report": SHA, "replay_report": SHA},
        alert_delivery_report=report,
        alert_delivery_report_sha256=SHA,
        incident_evidence_hashes={},
    )

    assert not next(
        check for check in result.checks if check.name == "alert_delivery_report"
    ).passed


def test_incident_evidence_hash_substitution_fails_closed() -> None:
    evidence = _evidence()
    evidence["incident_reconciliations"] = [
        {
            "incident_id": "INC-1",
            "collector_id": "btcusdt",
            "incident_type": "reconnect",
            "occurred_at_utc": "2026-08-22T12:00:00Z",
            "reconciled": True,
            "evidence_reference": "immutable://incident",
            "evidence_sha256": "c" * 64,
            "next_snapshot_connection_id": "connection-2",
            "replay_checksum": SHA,
        }
    ]

    result = _evaluate(soak=_soak(reconnects=1), evidence=evidence)

    assert not next(
        check for check in result.checks if check.name == "incident_reconciliation"
    ).passed
