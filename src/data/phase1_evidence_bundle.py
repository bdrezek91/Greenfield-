"""Immutable, content-addressed Phase 1 operational evidence bundle."""

from __future__ import annotations

import hashlib
import json
import os
import re
import time
import uuid
from collections.abc import Mapping
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from src.data.phase1_recovery_drill import DRILL_TYPES

CORE_ARTIFACT_ROLES = (
    "soak_session",
    "capacity_forecast",
    "soak_report",
    "replay_report",
    "alert_journal",
    "external_alert_receipt",
    "alert_delivery_report",
    "runtime_configuration",
)
REQUIRED_ARTIFACT_ROLES = CORE_ARTIFACT_ROLES + tuple(
    f"recovery_drill/{name}" for name in DRILL_TYPES
)
_ROLE = re.compile(r"^[a-z0-9][a-z0-9_./-]{1,127}$")
_GIT_SHA = re.compile(r"^[0-9a-f]{40}$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")


@dataclass(frozen=True, slots=True)
class EvidenceArtifact:
    role: str
    relative_path: str
    size_bytes: int
    sha256: str


@dataclass(frozen=True, slots=True)
class PhaseOneEvidenceBundle:
    schema_version: int
    session_id: str
    source_commit: str
    generated_at_utc: str
    artifacts: tuple[EvidenceArtifact, ...]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def artifact_hashes(self) -> dict[str, str]:
        return {item.role: item.sha256 for item in self.artifacts}


def create_phase1_evidence_bundle(
    *,
    root: Path,
    output_path: Path,
    session_id: str,
    source_commit: str,
    artifacts: Mapping[str, Path],
    now_ns: int | None = None,
) -> PhaseOneEvidenceBundle:
    """Hash required evidence and exclusively publish its portable manifest."""

    resolved_root = Path(root).resolve(strict=True)
    if not resolved_root.is_dir():
        raise ValueError("evidence root must be a directory")
    _validate_identity(session_id=session_id, source_commit=source_commit)
    missing = sorted(set(REQUIRED_ARTIFACT_ROLES) - set(artifacts))
    if missing:
        raise ValueError(f"missing required evidence artifact roles: {missing}")

    resolved_output = Path(output_path).resolve()
    try:
        resolved_output.relative_to(resolved_root)
    except ValueError as exc:
        raise ValueError("evidence bundle output must stay inside root") from exc
    entries: list[EvidenceArtifact] = []
    observed_paths: set[Path] = set()
    for role, path in sorted(artifacts.items()):
        if not _ROLE.fullmatch(role):
            raise ValueError(f"invalid evidence artifact role: {role!r}")
        resolved = _resolve_contained_file(resolved_root, path)
        if resolved == resolved_output:
            raise ValueError("evidence bundle cannot include its own manifest")
        if resolved in observed_paths:
            raise ValueError(f"duplicate evidence artifact path: {resolved}")
        observed_paths.add(resolved)
        raw = resolved.read_bytes()
        entries.append(
            EvidenceArtifact(
                role=role,
                relative_path=resolved.relative_to(resolved_root).as_posix(),
                size_bytes=len(raw),
                sha256=hashlib.sha256(raw).hexdigest(),
            )
        )

    timestamp_ns = time.time_ns() if now_ns is None else now_ns
    bundle = PhaseOneEvidenceBundle(
        schema_version=1,
        session_id=session_id,
        source_commit=source_commit,
        generated_at_utc=datetime.fromtimestamp(
            timestamp_ns / 1_000_000_000, tz=UTC
        ).isoformat(),
        artifacts=tuple(entries),
    )
    _write_exclusive(output_path, json.dumps(bundle.to_dict(), sort_keys=True, indent=2))
    return bundle


def load_and_verify_phase1_evidence_bundle(
    *,
    path: Path,
    root: Path,
    expected_session_id: str,
    expected_commit: str,
) -> tuple[PhaseOneEvidenceBundle, str]:
    """Load a bundle and re-hash every referenced file before accepting it."""

    resolved_root = Path(root).resolve(strict=True)
    raw_manifest = Path(path).read_bytes()
    value = json.loads(raw_manifest)
    if not isinstance(value, dict) or value.get("schema_version") != 1:
        raise ValueError("invalid Phase 1 evidence bundle schema")
    if value.get("session_id") != expected_session_id:
        raise ValueError("evidence bundle session does not match the soak")
    if value.get("source_commit") != expected_commit:
        raise ValueError("evidence bundle commit does not match the deployment")
    _validate_identity(session_id=expected_session_id, source_commit=expected_commit)
    _validate_timestamp(value.get("generated_at_utc"))

    raw_entries = value.get("artifacts")
    if not isinstance(raw_entries, list):
        raise ValueError("evidence bundle artifacts must be a list")
    entries: list[EvidenceArtifact] = []
    roles: set[str] = set()
    paths: set[Path] = set()
    for raw_entry in raw_entries:
        if not isinstance(raw_entry, dict):
            raise ValueError("malformed evidence artifact entry")
        try:
            entry = EvidenceArtifact(
                role=str(raw_entry["role"]),
                relative_path=str(raw_entry["relative_path"]),
                size_bytes=int(raw_entry["size_bytes"]),
                sha256=str(raw_entry["sha256"]),
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError("malformed evidence artifact entry") from exc
        if not _ROLE.fullmatch(entry.role) or entry.role in roles:
            raise ValueError(f"invalid or duplicate evidence role: {entry.role!r}")
        if entry.size_bytes < 0 or not _valid_sha256(entry.sha256):
            raise ValueError(f"invalid metadata for evidence role {entry.role!r}")
        artifact_path = _resolve_contained_file(resolved_root, Path(entry.relative_path))
        if artifact_path in paths:
            raise ValueError(f"duplicate evidence artifact path: {artifact_path}")
        raw = artifact_path.read_bytes()
        if len(raw) != entry.size_bytes or hashlib.sha256(raw).hexdigest() != entry.sha256:
            raise ValueError(f"evidence artifact changed after bundling: {entry.role}")
        roles.add(entry.role)
        paths.add(artifact_path)
        entries.append(entry)

    missing = sorted(set(REQUIRED_ARTIFACT_ROLES) - roles)
    if missing:
        raise ValueError(f"evidence bundle lacks required roles: {missing}")
    bundle = PhaseOneEvidenceBundle(
        schema_version=1,
        session_id=expected_session_id,
        source_commit=expected_commit,
        generated_at_utc=str(value["generated_at_utc"]),
        artifacts=tuple(entries),
    )
    return bundle, hashlib.sha256(raw_manifest).hexdigest()


def _resolve_contained_file(root: Path, path: Path) -> Path:
    candidate = path if path.is_absolute() else root / path
    resolved = candidate.resolve(strict=True)
    try:
        resolved.relative_to(root)
    except ValueError as exc:
        raise ValueError(f"evidence artifact escapes root: {path}") from exc
    if not resolved.is_file():
        raise ValueError(f"evidence artifact is not a regular file: {path}")
    return resolved


def _validate_identity(*, session_id: str, source_commit: str) -> None:
    if not session_id.strip() or session_id.lower() in {"replace-me", "todo", "tbd"}:
        raise ValueError("evidence bundle requires a non-placeholder session ID")
    if not _GIT_SHA.fullmatch(source_commit) or set(source_commit) == {"0"}:
        raise ValueError("evidence bundle requires a nonzero lowercase Git SHA")


def _validate_timestamp(value: Any) -> None:
    if not isinstance(value, str):
        raise ValueError("evidence bundle lacks generated_at_utc")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError("invalid evidence bundle timestamp") from exc
    if parsed.tzinfo is None:
        raise ValueError("evidence bundle timestamp must include a timezone")


def _write_exclusive(path: Path, value: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    try:
        with temporary.open("x", encoding="utf-8", newline="\n") as handle:
            handle.write(value + "\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.link(temporary, path)
    except FileExistsError as exc:
        raise FileExistsError(
            f"evidence bundle already exists and will not be overwritten: {path}"
        ) from exc
    finally:
        temporary.unlink(missing_ok=True)


def _valid_sha256(value: str) -> bool:
    return bool(_SHA256.fullmatch(value)) and set(value) != {"0"}
