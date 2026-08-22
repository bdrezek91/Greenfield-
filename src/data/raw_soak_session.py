"""Immutable provenance marker for a measured Phase 1 seven-day soak."""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import time
import uuid
from collections.abc import Sequence
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

MINIMUM_SOAK_DURATION_SECS = 7 * 24 * 60 * 60
DEFAULT_MAX_PREFLIGHT_AGE_SECS = 15 * 60
DEFAULT_MAX_CAPACITY_FORECAST_AGE_SECS = 15 * 60
_SESSION_ID = re.compile(r"^[a-z0-9][a-z0-9-]{2,63}$")
_GIT_SHA = re.compile(r"^[0-9a-f]{40}$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")


@dataclass(frozen=True, slots=True)
class RawSoakSession:
    schema_version: int
    session_id: str
    started_at_utc: str
    start_ts_ns: int
    source_commit: str
    minimum_duration_secs: int
    collector_ids: tuple[str, ...]
    preflight_report_path: str
    preflight_report_sha256: str
    capacity_forecast_report_path: str
    capacity_forecast_report_sha256: str
    config_sha256: dict[str, str]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def create_raw_soak_session(
    *,
    session_id: str,
    source_commit: str,
    preflight_report_path: Path,
    capacity_forecast_report_path: Path,
    expected_data_dir: Path,
    config_paths: Sequence[Path],
    output_path: Path,
    collector_ids: tuple[str, ...] = ("btcusdt", "ethusdt", "solusdt"),
    now_ns: int | None = None,
    max_preflight_age_secs: float = DEFAULT_MAX_PREFLIGHT_AGE_SECS,
    max_capacity_forecast_age_secs: float = DEFAULT_MAX_CAPACITY_FORECAST_AGE_SECS,
) -> RawSoakSession:
    """Validate fresh preflight evidence and exclusively create a soak marker."""

    if not _SESSION_ID.fullmatch(session_id):
        raise ValueError("session_id must be 3-64 lowercase letters, digits, or hyphens")
    if not _GIT_SHA.fullmatch(source_commit) or set(source_commit) == {"0"}:
        raise ValueError("source_commit must be a nonzero 40-character lowercase Git SHA")
    if max_preflight_age_secs <= 0:
        raise ValueError("max_preflight_age_secs must be positive")
    if max_capacity_forecast_age_secs <= 0:
        raise ValueError("max_capacity_forecast_age_secs must be positive")
    if not collector_ids or len(set(collector_ids)) != len(collector_ids):
        raise ValueError("collector_ids must be nonempty and unique")
    if not config_paths:
        raise ValueError("at least one configuration file is required")

    preflight_path = Path(preflight_report_path).resolve()
    preflight_bytes = preflight_path.read_bytes()
    preflight = json.loads(preflight_bytes)
    if not isinstance(preflight, dict):
        raise ValueError("preflight report must be a JSON object")
    if preflight.get("schema_version") != 1 or preflight.get("qualified") is not True:
        raise ValueError("preflight report is not qualified schema version 1 evidence")
    if preflight.get("expected_commit") != source_commit:
        raise ValueError("preflight report commit does not match source_commit")
    observations = preflight.get("observations")
    if not isinstance(observations, dict):
        raise ValueError("preflight report lacks observations")
    if observations.get("source_commit") != source_commit:
        raise ValueError("preflight observation commit does not match source_commit")
    if observations.get("working_tree_clean") is not True:
        raise ValueError("preflight observation did not prove a clean worktree")

    current_ns = time.time_ns() if now_ns is None else now_ns
    generated_ns = _timestamp_ns(preflight.get("generated_at_utc"), "preflight")
    age_secs = (current_ns - generated_ns) / 1_000_000_000
    if age_secs < -60:
        raise ValueError("preflight report timestamp is in the future")
    if age_secs > max_preflight_age_secs:
        raise ValueError(
            f"preflight report is stale ({age_secs:.1f}s > {max_preflight_age_secs:.1f}s)"
        )

    capacity_path = Path(capacity_forecast_report_path).resolve()
    capacity_bytes = capacity_path.read_bytes()
    capacity = json.loads(capacity_bytes)
    if not isinstance(capacity, dict):
        raise ValueError("capacity forecast report must be a JSON object")
    if capacity.get("schema_version") != 1 or capacity.get("qualified") is not True:
        raise ValueError("capacity forecast is not qualified schema version 1 evidence")
    if capacity.get("source_commit") != source_commit:
        raise ValueError("capacity forecast commit does not match source_commit")
    data_dir = Path(expected_data_dir).resolve(strict=True)
    try:
        forecast_data_dir = Path(str(capacity["target_data_dir"])).resolve(strict=True)
    except (KeyError, OSError) as exc:
        raise ValueError("capacity forecast target data directory is invalid") from exc
    if forecast_data_dir != data_dir:
        raise ValueError("capacity forecast target does not match expected data directory")
    capacity_generated_ns = _timestamp_ns(
        capacity.get("generated_at_utc"), "capacity forecast"
    )
    capacity_age_secs = (current_ns - capacity_generated_ns) / 1_000_000_000
    if capacity_age_secs < -60:
        raise ValueError("capacity forecast timestamp is in the future")
    if capacity_age_secs > max_capacity_forecast_age_secs:
        raise ValueError(
            "capacity forecast is stale "
            f"({capacity_age_secs:.1f}s > {max_capacity_forecast_age_secs:.1f}s)"
        )
    capacity_checks = capacity.get("checks")
    if (
        not isinstance(capacity_checks, dict)
        or not capacity_checks
        or not all(value is True for value in capacity_checks.values())
    ):
        raise ValueError("capacity forecast contains a failed or malformed check")
    required_capacity = _positive_int(
        capacity.get("required_capacity_bytes"), "capacity required bytes"
    )
    reported_available = _positive_int(
        capacity.get("available_capacity_bytes"), "capacity available bytes"
    )
    if required_capacity > reported_available:
        raise ValueError("capacity forecast required bytes exceed reported availability")
    current_free = shutil.disk_usage(data_dir).free
    if current_free < required_capacity:
        raise ValueError(
            f"current free capacity {current_free} is below required {required_capacity}"
        )

    config_hashes: dict[str, str] = {}
    for config_path in config_paths:
        resolved = Path(config_path).resolve()
        if not resolved.is_file():
            raise ValueError(f"configuration file does not exist: {resolved.name}")
        key = resolved.name
        if key in config_hashes:
            raise ValueError(f"duplicate configuration filename: {key}")
        config_hashes[key] = hashlib.sha256(resolved.read_bytes()).hexdigest()

    session = RawSoakSession(
        schema_version=2,
        session_id=session_id,
        started_at_utc=datetime.fromtimestamp(current_ns / 1_000_000_000, tz=UTC).isoformat(),
        start_ts_ns=current_ns,
        source_commit=source_commit,
        minimum_duration_secs=MINIMUM_SOAK_DURATION_SECS,
        collector_ids=collector_ids,
        preflight_report_path=str(preflight_path),
        preflight_report_sha256=hashlib.sha256(preflight_bytes).hexdigest(),
        capacity_forecast_report_path=str(capacity_path),
        capacity_forecast_report_sha256=hashlib.sha256(capacity_bytes).hexdigest(),
        config_sha256=dict(sorted(config_hashes.items())),
    )
    document = json.dumps(session.to_dict(), sort_keys=True, indent=2) + "\n"
    _write_exclusive(Path(output_path), document)
    return session


def load_raw_soak_session(path: Path) -> RawSoakSession:
    value = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(value, dict) or value.get("schema_version") != 2:
        raise ValueError("invalid raw soak session schema")
    try:
        session = RawSoakSession(
            schema_version=2,
            session_id=str(value["session_id"]),
            started_at_utc=str(value["started_at_utc"]),
            start_ts_ns=int(value["start_ts_ns"]),
            source_commit=str(value["source_commit"]),
            minimum_duration_secs=int(value["minimum_duration_secs"]),
            collector_ids=tuple(str(item) for item in value["collector_ids"]),
            preflight_report_path=str(value["preflight_report_path"]),
            preflight_report_sha256=str(value["preflight_report_sha256"]),
            capacity_forecast_report_path=str(
                value["capacity_forecast_report_path"]
            ),
            capacity_forecast_report_sha256=str(
                value["capacity_forecast_report_sha256"]
            ),
            config_sha256={str(key): str(item) for key, item in value["config_sha256"].items()},
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError("malformed raw soak session") from exc
    if not _SESSION_ID.fullmatch(session.session_id):
        raise ValueError("invalid raw soak session ID")
    if session.minimum_duration_secs < MINIMUM_SOAK_DURATION_SECS:
        raise ValueError("raw soak session duration is below seven days")
    if not _GIT_SHA.fullmatch(session.source_commit) or set(session.source_commit) == {"0"}:
        raise ValueError("invalid raw soak session commit")
    if session.start_ts_ns <= 0 or abs(
        _timestamp_ns(session.started_at_utc, "soak session") - session.start_ts_ns
    ) > 1_000:
        raise ValueError("raw soak session UTC timestamp does not match start_ts_ns")
    if not session.collector_ids or len(set(session.collector_ids)) != len(
        session.collector_ids
    ):
        raise ValueError("invalid raw soak collector set")
    if not _valid_sha256(session.preflight_report_sha256):
        raise ValueError("invalid raw soak preflight hash")
    if not _valid_sha256(session.capacity_forecast_report_sha256):
        raise ValueError("invalid raw soak capacity forecast hash")
    if not session.config_sha256 or not all(
        _valid_sha256(item) for item in session.config_sha256.values()
    ):
        raise ValueError("invalid raw soak configuration hashes")
    return session


def file_sha256(path: Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _timestamp_ns(value: Any, label: str) -> int:
    if not isinstance(value, str):
        raise ValueError(f"{label} report lacks generated_at_utc")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError(f"{label} generated_at_utc is invalid") from exc
    if parsed.tzinfo is None:
        raise ValueError(f"{label} generated_at_utc must include a timezone")
    return int(parsed.timestamp() * 1_000_000_000)


def _positive_int(value: Any, label: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
        raise ValueError(f"{label} must be a positive integer")
    return value


def _write_exclusive(path: Path, value: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    try:
        with temp_path.open("x", encoding="utf-8", newline="\n") as handle:
            handle.write(value)
            handle.flush()
            os.fsync(handle.fileno())
        # A hard-link publish is atomic and refuses an existing destination;
        # unlike writing the final path directly, a crash cannot expose a
        # truncated marker that looks like the authoritative session.
        os.link(temp_path, path)
    except FileExistsError as exc:
        raise FileExistsError(
            f"soak session already exists and will not be overwritten: {path}"
        ) from exc
    finally:
        temp_path.unlink(missing_ok=True)


def _valid_sha256(value: str) -> bool:
    return bool(_SHA256.fullmatch(value)) and set(value) != {"0"}
