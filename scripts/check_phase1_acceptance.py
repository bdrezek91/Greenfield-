"""Evaluate all Greenfield v2 Phase 1 exit evidence as one fail-closed gate."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Annotated, Any

import typer
import yaml

from src.data.phase1_acceptance import (
    REQUIRED_DRILLS,
    evaluate_phase1_acceptance,
    write_acceptance_report,
)
from src.data.phase1_evidence_bundle import load_and_verify_phase1_evidence_bundle
from src.data.raw_soak_session import load_raw_soak_session

app = typer.Typer(add_completion=False)


@app.command()
def check(
    source_commit: Annotated[
        str, typer.Option(help="Exact 40-character deployed Git commit SHA.")
    ],
    soak_report: Annotated[
        Path, typer.Option(help="Qualified seven-day soak JSON report.")
    ] = Path("reports/raw_collector_soak.json"),
    replay_report: Annotated[
        Path, typer.Option(help="Strict full-lake replay JSON report.")
    ] = Path("reports/raw_replay.json"),
    operational_evidence: Annotated[
        Path, typer.Option(help="Reviewed Phase 1 operational evidence YAML.")
    ] = Path("reports/phase1_operational_evidence.yaml"),
    evidence_root: Annotated[
        Path, typer.Option(help="Root used by portable evidence-bundle paths.")
    ] = Path("."),
    report_path: Annotated[
        Path, typer.Option(help="Atomic acceptance report output.")
    ] = Path("reports/phase1_acceptance.json"),
) -> None:
    try:
        soak = _load_json(soak_report)
        replay = _load_json(replay_report)
        evidence = _load_yaml(operational_evidence)
        drill_reports, drill_report_hashes = _load_drill_reports(
            evidence, root=evidence_root
        )
        alert_report, alert_report_sha256 = _load_alert_report(
            evidence, root=evidence_root
        )
        incident_hashes = _load_incident_evidence(evidence, root=evidence_root)
        bundle_path = _bundle_path(evidence, evidence_root)
        bundle, bundle_sha256 = load_and_verify_phase1_evidence_bundle(
            path=bundle_path,
            root=evidence_root,
            expected_session_id=str(soak.get("session_id", "")),
            expected_commit=source_commit,
        )
        source_file_hashes = {
            "soak_report": _file_sha256(soak_report),
            "replay_report": _file_sha256(replay_report),
        }
        session_path = _bundle_artifact_path(bundle, "soak_session", evidence_root)
        capacity_path = _bundle_artifact_path(
            bundle, "capacity_forecast", evidence_root
        )
        session = load_raw_soak_session(session_path)
        capacity = _load_json(capacity_path)
        capacity_sha256 = _file_sha256(capacity_path)
    except (OSError, json.JSONDecodeError, yaml.YAMLError, ValueError) as exc:
        typer.echo(f"invalid Phase 1 evidence input: {exc}", err=True)
        raise typer.Exit(code=2) from exc
    report = evaluate_phase1_acceptance(
        soak_report=soak,
        replay_report=replay,
        operational_evidence=evidence,
        expected_commit=source_commit,
        drill_reports=drill_reports,
        drill_report_hashes=drill_report_hashes,
        evidence_bundle=bundle.to_dict(),
        evidence_bundle_sha256=bundle_sha256,
        bundle_artifact_hashes=bundle.artifact_hashes(),
        source_file_hashes=source_file_hashes,
        alert_delivery_report=alert_report,
        alert_delivery_report_sha256=alert_report_sha256,
        incident_evidence_hashes=incident_hashes,
        soak_session=session.to_dict(),
        capacity_forecast_report=capacity,
        capacity_forecast_report_sha256=capacity_sha256,
    )
    write_acceptance_report(report_path, report)
    typer.echo(json.dumps(report.to_dict(), sort_keys=True, indent=2))
    if not report.qualified:
        raise typer.Exit(code=1)


def _load_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return value


def _load_yaml(path: Path) -> dict[str, Any]:
    value = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{path} must contain a YAML mapping")
    return value


def _load_drill_reports(
    operational_evidence: dict[str, Any],
    *,
    root: Path,
) -> tuple[dict[str, dict[str, Any]], dict[str, str]]:
    drills = operational_evidence.get("drills")
    if not isinstance(drills, dict):
        raise ValueError("operational evidence must contain a drills mapping")
    reports: dict[str, dict[str, Any]] = {}
    hashes: dict[str, str] = {}
    for name in REQUIRED_DRILLS:
        drill = drills.get(name)
        if not isinstance(drill, dict):
            raise ValueError(f"missing drill evidence: {name}")
        reference = drill.get("evidence_reference")
        if not isinstance(reference, str) or not reference.strip():
            raise ValueError(f"drill {name} lacks evidence_reference")
        path = Path(reference)
        if not path.is_absolute():
            path = root / path
        raw = path.read_bytes()
        value = json.loads(raw)
        if not isinstance(value, dict):
            raise ValueError(f"{path} must contain a JSON object")
        reports[name] = value
        hashes[name] = hashlib.sha256(raw).hexdigest()
    return reports, hashes


def _bundle_path(operational_evidence: dict[str, Any], root: Path) -> Path:
    approval = operational_evidence.get("operator_approval")
    if not isinstance(approval, dict):
        raise ValueError("operational evidence must contain operator_approval")
    reference = approval.get("evidence_bundle_reference")
    if not isinstance(reference, str) or not reference.strip():
        raise ValueError("operator approval lacks evidence_bundle_reference")
    path = Path(reference)
    return path if path.is_absolute() else root / path


def _load_alert_report(
    operational_evidence: dict[str, Any], *, root: Path
) -> tuple[dict[str, Any], str]:
    alert = operational_evidence.get("alert_delivery")
    if not isinstance(alert, dict):
        raise ValueError("operational evidence must contain alert_delivery")
    reference = alert.get("evidence_reference")
    if not isinstance(reference, str) or not reference.strip():
        raise ValueError("alert delivery lacks evidence_reference")
    path = Path(reference)
    if not path.is_absolute():
        path = root / path
    raw = path.read_bytes()
    value = json.loads(raw)
    if not isinstance(value, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return value, hashlib.sha256(raw).hexdigest()


def _file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _bundle_artifact_path(bundle: Any, role: str, root: Path) -> Path:
    matches = [item for item in bundle.artifacts if item.role == role]
    if len(matches) != 1:
        raise ValueError(f"evidence bundle must contain exactly one {role} artifact")
    return root / matches[0].relative_path


def _load_incident_evidence(
    operational_evidence: dict[str, Any], *, root: Path
) -> dict[str, str]:
    incidents = operational_evidence.get("incident_reconciliations")
    if not isinstance(incidents, list):
        raise ValueError("incident_reconciliations must be a list")
    hashes: dict[str, str] = {}
    for incident in incidents:
        if not isinstance(incident, dict):
            raise ValueError("incident reconciliation entries must be mappings")
        incident_id = incident.get("incident_id")
        reference = incident.get("evidence_reference")
        if not isinstance(incident_id, str) or not incident_id.strip():
            raise ValueError("incident reconciliation lacks incident_id")
        if incident_id in hashes:
            raise ValueError(f"duplicate incident ID: {incident_id}")
        if not isinstance(reference, str) or not reference.strip():
            raise ValueError(f"incident {incident_id} lacks evidence_reference")
        path = Path(reference)
        if not path.is_absolute():
            path = root / path
        hashes[incident_id] = _file_sha256(path)
    return hashes


if __name__ == "__main__":
    app()
