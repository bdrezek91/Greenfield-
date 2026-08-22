"""Fail-closed binding between a raw collector process and its soak marker."""

from __future__ import annotations

import re
import time
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from src.data.raw_soak_session import file_sha256, load_raw_soak_session

_SESSION_ID = re.compile(r"^[a-z0-9][a-z0-9-]{2,63}$")
_GIT_SHA = re.compile(r"^[0-9a-f]{40}$")


@dataclass(frozen=True, slots=True)
class RawCollectorStartBinding:
    session_id: str
    source_commit: str
    collector_id: str
    marker_path: Path


def validate_raw_collector_start(
    *,
    data_dir: Path,
    session_id: str,
    deployed_commit: str,
    collector_id: str,
    config_paths: Sequence[Path],
    now_ns: int | None = None,
) -> RawCollectorStartBinding:
    """Require one exact immutable session before opening a market connection."""

    if not _SESSION_ID.fullmatch(session_id):
        raise ValueError("GREENFIELD_SOAK_ID is missing or invalid")
    if not _GIT_SHA.fullmatch(deployed_commit) or set(deployed_commit) == {"0"}:
        raise ValueError("GREENFIELD_DEPLOY_COMMIT is missing or invalid")
    if not collector_id.strip():
        raise ValueError("collector_id is required")
    if not config_paths:
        raise ValueError("at least one bound configuration file is required")

    resolved_data_dir = Path(data_dir).resolve(strict=True)
    marker_path = (
        resolved_data_dir / "health" / "soak_sessions" / f"{session_id}.json"
    ).resolve(strict=True)
    expected_parent = (resolved_data_dir / "health" / "soak_sessions").resolve()
    if marker_path.parent != expected_parent:
        raise ValueError("soak marker escaped the configured data directory")

    session = load_raw_soak_session(marker_path)
    if session.session_id != session_id:
        raise ValueError("soak marker session does not match GREENFIELD_SOAK_ID")
    if session.source_commit != deployed_commit:
        raise ValueError("soak marker commit does not match GREENFIELD_DEPLOY_COMMIT")
    if collector_id not in session.collector_ids:
        raise ValueError("collector_id is not authorized by the soak marker")
    current_ns = time.time_ns() if now_ns is None else now_ns
    if session.start_ts_ns > current_ns + 60 * 1_000_000_000:
        raise ValueError("soak marker start time is in the future")

    seen_names: set[str] = set()
    for config_path in config_paths:
        resolved = Path(config_path).resolve(strict=True)
        if resolved.name in seen_names:
            raise ValueError(f"duplicate bound configuration filename: {resolved.name}")
        seen_names.add(resolved.name)
        expected_hash = session.config_sha256.get(resolved.name)
        if expected_hash is None:
            raise ValueError(f"soak marker does not bind configuration: {resolved.name}")
        if file_sha256(resolved) != expected_hash:
            raise ValueError(f"configuration changed after soak marker: {resolved.name}")

    return RawCollectorStartBinding(
        session_id=session.session_id,
        source_commit=session.source_commit,
        collector_id=collector_id,
        marker_path=marker_path,
    )
