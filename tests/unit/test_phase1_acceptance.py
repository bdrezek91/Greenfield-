"""Phase 1 cannot pass without complete, reconciled operational evidence."""

from __future__ import annotations

from copy import deepcopy
from pathlib import Path

from src.data.phase1_acceptance import (
    REQUIRED_DRILLS,
    evaluate_phase1_acceptance,
    write_acceptance_report,
)

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
        "replay_checksum": SHA,
    }
    return {
        "schema_version": 1,
        "source_commit": COMMIT,
        "alert_delivery": {
            "passed": True,
            "tested_at_utc": "2026-08-22T12:00:00Z",
            "journal_event_id": SHA,
            "durable_journal_evidence": "immutable://journal",
            "external_delivery_evidence": "immutable://operator-channel",
        },
        "drills": {name: deepcopy(drill) for name in REQUIRED_DRILLS},
        "incident_reconciliations": [],
        "operator_approval": {
            "approved": True,
            "operator": "operator",
            "approved_at_utc": "2026-08-22T13:00:00+00:00",
            "evidence_bundle_reference": "immutable://phase1-bundle",
        },
    }


def test_complete_phase1_evidence_qualifies_and_is_hashed(tmp_path: Path) -> None:
    report = evaluate_phase1_acceptance(
        soak_report=_soak(),
        replay_report=_replay(),
        operational_evidence=_evidence(),
        expected_commit=COMMIT,
    )

    assert report.qualified
    assert len(report.input_sha256) == 3
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

    report = evaluate_phase1_acceptance(
        soak_report=soak,
        replay_report=replay,
        operational_evidence=evidence,
        expected_commit=COMMIT,
    )

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
        "next_snapshot_connection_id": "connection-2",
        "replay_checksum": SHA,
    }
    evidence["incident_reconciliations"] = [base_incident]

    incomplete = evaluate_phase1_acceptance(
        soak_report=_soak(reconnects=1, uncertainties=1),
        replay_report=_replay(),
        operational_evidence=evidence,
        expected_commit=COMMIT,
    )
    assert not next(
        check for check in incomplete.checks if check.name == "incident_reconciliation"
    ).passed

    uncertainty = deepcopy(base_incident)
    uncertainty.update(incident_id="INC-2", incident_type="sequence_uncertainty")
    evidence["incident_reconciliations"].append(uncertainty)
    complete = evaluate_phase1_acceptance(
        soak_report=_soak(reconnects=1, uncertainties=1),
        replay_report=_replay(),
        operational_evidence=evidence,
        expected_commit=COMMIT,
    )
    assert complete.qualified


def test_commit_mismatch_and_placeholder_operator_approval_fail() -> None:
    evidence = _evidence()
    evidence["operator_approval"]["approved"] = False
    report = evaluate_phase1_acceptance(
        soak_report=_soak(),
        replay_report=_replay(),
        operational_evidence=evidence,
        expected_commit="c" * 40,
    )
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
        "next_snapshot_connection_id": "connection-2",
        "replay_checksum": SHA,
    }
    evidence["incident_reconciliations"] = [incident, deepcopy(incident)]
    evidence["drills"]["storage_restore"]["operator"] = "replace-me"

    report = evaluate_phase1_acceptance(
        soak_report=_soak(reconnects=1),
        replay_report=_replay(),
        operational_evidence=evidence,
        expected_commit=COMMIT,
    )

    failed = {check.name for check in report.checks if not check.passed}
    assert {"incident_reconciliation", "recovery_drills"} <= failed
