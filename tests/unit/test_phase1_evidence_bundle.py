"""Phase 1 bundle manifests are portable, immutable, and content-addressed."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.data.phase1_evidence_bundle import (
    REQUIRED_ARTIFACT_ROLES,
    create_phase1_evidence_bundle,
    load_and_verify_phase1_evidence_bundle,
)

COMMIT = "b" * 40
SESSION = "phase1-session"


def _artifacts(root: Path) -> dict[str, Path]:
    values = {}
    for index, role in enumerate(REQUIRED_ARTIFACT_ROLES):
        path = root / "artifacts" / f"artifact-{index}.txt"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(f"{role}\n", encoding="utf-8")
        values[role] = path
    return values


def test_bundle_round_trip_rehashes_every_artifact(tmp_path: Path) -> None:
    output = tmp_path / "reports" / "phase1-evidence-bundle.json"
    bundle = create_phase1_evidence_bundle(
        root=tmp_path,
        output_path=output,
        session_id=SESSION,
        source_commit=COMMIT,
        artifacts=_artifacts(tmp_path),
        now_ns=1_800_000_000_000_000_000,
    )

    verified, manifest_sha256 = load_and_verify_phase1_evidence_bundle(
        path=output,
        root=tmp_path,
        expected_session_id=SESSION,
        expected_commit=COMMIT,
    )

    assert verified == bundle
    assert len(manifest_sha256) == 64
    assert set(verified.artifact_hashes()) == set(REQUIRED_ARTIFACT_ROLES)
    with pytest.raises(FileExistsError, match="will not be overwritten"):
        create_phase1_evidence_bundle(
            root=tmp_path,
            output_path=output,
            session_id=SESSION,
            source_commit=COMMIT,
            artifacts=_artifacts(tmp_path),
        )


def test_missing_role_and_outside_root_fail_closed(tmp_path: Path) -> None:
    artifacts = _artifacts(tmp_path)
    del artifacts["alert_journal"]
    with pytest.raises(ValueError, match="missing required"):
        create_phase1_evidence_bundle(
            root=tmp_path,
            output_path=tmp_path / "bundle.json",
            session_id=SESSION,
            source_commit=COMMIT,
            artifacts=artifacts,
        )

    outside = tmp_path.parent / f"{tmp_path.name}-outside-evidence.txt"
    outside.write_text("outside", encoding="utf-8")
    artifacts = _artifacts(tmp_path)
    artifacts["alert_journal"] = outside
    with pytest.raises(ValueError, match="escapes root"):
        create_phase1_evidence_bundle(
            root=tmp_path,
            output_path=tmp_path / "bundle.json",
            session_id=SESSION,
            source_commit=COMMIT,
            artifacts=artifacts,
        )
    outside.unlink()


def test_tampered_artifact_or_manifest_is_rejected(tmp_path: Path) -> None:
    artifacts = _artifacts(tmp_path)
    output = tmp_path / "bundle.json"
    create_phase1_evidence_bundle(
        root=tmp_path,
        output_path=output,
        session_id=SESSION,
        source_commit=COMMIT,
        artifacts=artifacts,
    )
    artifacts["replay_report"].write_text("changed\n", encoding="utf-8")
    with pytest.raises(ValueError, match="changed after bundling"):
        load_and_verify_phase1_evidence_bundle(
            path=output,
            root=tmp_path,
            expected_session_id=SESSION,
            expected_commit=COMMIT,
        )

    value = json.loads(output.read_text(encoding="utf-8"))
    value["source_commit"] = "c" * 40
    output.write_text(json.dumps(value), encoding="utf-8")
    with pytest.raises(ValueError, match="commit"):
        load_and_verify_phase1_evidence_bundle(
            path=output,
            root=tmp_path,
            expected_session_id=SESSION,
            expected_commit=COMMIT,
        )
