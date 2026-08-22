"""Machine-verifiable evidence for the five Phase 1 recovery drills."""

from __future__ import annotations

import json
import os
import re
import uuid
from collections.abc import Mapping
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from src.data.raw_soak_session import RawSoakSession

DRILL_TYPES = (
    "graceful_sigterm",
    "process_restart",
    "vps_reboot",
    "disk_backlog",
    "storage_restore",
)
EXPECTED_SYMBOLS = ("BTCUSDT", "ETHUSDT", "SOLUSDT")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")


@dataclass(frozen=True, slots=True)
class DrillCheck:
    name: str
    passed: bool
    detail: str


@dataclass(frozen=True, slots=True)
class PhaseOneRecoveryDrillReport:
    schema_version: int
    drill_type: str
    qualified: bool
    session_id: str
    source_commit: str
    operator: str
    started_at_utc: str
    completed_at_utc: str
    replay_checksum: str
    checks: tuple[DrillCheck, ...]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def evaluate_phase1_recovery_drill(
    *,
    drill_type: str,
    session: RawSoakSession,
    before_health: Mapping[str, Mapping[str, Any]],
    after_health: Mapping[str, Mapping[str, Any]],
    replay_report: Mapping[str, Any],
    operator: str,
    started_at_utc: str,
    completed_at_utc: str,
    transition_health: Mapping[str, Mapping[str, Any]] | None = None,
    boot_id_before: str | None = None,
    boot_id_after: str | None = None,
    peak_queue_depth: int | None = None,
    queue_capacity: int | None = None,
    storage_source_sha256: str | None = None,
    storage_restored_sha256: str | None = None,
) -> PhaseOneRecoveryDrillReport:
    if drill_type not in DRILL_TYPES:
        raise ValueError(f"unknown drill_type {drill_type!r}")
    checks: list[DrillCheck] = []

    def check(name: str, passed: bool, detail: str) -> None:
        checks.append(DrillCheck(name, bool(passed), detail))

    started_ns = _timestamp_ns(started_at_utc)
    completed_ns = _timestamp_ns(completed_at_utc)
    check(
        "drill_timeline",
        session.start_ts_ns <= started_ns < completed_ns,
        (
            f"session_start_ns={session.start_ts_ns}; started_ns={started_ns}; "
            f"completed_ns={completed_ns}"
        ),
    )
    check(
        "named_operator",
        _meaningful(operator),
        "operator must be a non-placeholder identity",
    )

    expected_collectors = set(session.collector_ids)
    check(
        "health_snapshot_sets",
        set(before_health) == expected_collectors
        and set(after_health) == expected_collectors,
        (
            f"before={sorted(before_health)}; after={sorted(after_health)}; "
            f"expected={sorted(expected_collectors)}"
        ),
    )
    before_clean = all(
        _valid_before_snapshot(collector_id, before_health.get(collector_id, {}))
        for collector_id in session.collector_ids
    )
    after_recovered = all(
        _valid_after_snapshot(
            collector_id,
            after_health.get(collector_id, {}),
            completed_ns=completed_ns,
        )
        for collector_id in session.collector_ids
    )
    check(
        "healthy_before",
        before_clean,
        "all collectors running/connected with zero loss or uncertainty before drill",
    )
    check(
        "healthy_recovery",
        after_recovered,
        "all collectors running, flushed, connected, and lossless after drill",
    )

    connection_change_required = drill_type in {
        "graceful_sigterm",
        "process_restart",
        "vps_reboot",
    }
    changed_connections = all(
        _meaningful(before_health.get(collector_id, {}).get("connection_id"))
        and _meaningful(after_health.get(collector_id, {}).get("connection_id"))
        and before_health.get(collector_id, {}).get("connection_id")
        != after_health.get(collector_id, {}).get("connection_id")
        for collector_id in session.collector_ids
    )
    check(
        "new_connections",
        changed_connections if connection_change_required else True,
        f"required={connection_change_required}; changed_for_all={changed_connections}",
    )

    replay_checksum = str(replay_report.get("replay_checksum", ""))
    replay_ok = _valid_replay(replay_report)
    check(
        "strict_replay_after_drill",
        replay_ok,
        (
            f"checksum={replay_checksum or '<missing>'}; "
            f"symbols={sorted(_mapping(replay_report.get('orderbooks')))}"
        ),
    )

    if drill_type == "graceful_sigterm":
        transition = transition_health or {}
        stopped_cleanly = set(transition) == expected_collectors and all(
            _valid_stopped_snapshot(collector_id, transition.get(collector_id, {}))
            for collector_id in session.collector_ids
        )
        check(
            "graceful_flush_boundary",
            stopped_cleanly,
            "every stopped snapshot must be disconnected, queue=0, and received=written",
        )
    elif drill_type == "vps_reboot":
        boot_changed = (
            _meaningful(boot_id_before)
            and _meaningful(boot_id_after)
            and boot_id_before != boot_id_after
        )
        check(
            "host_boot_identity_changed",
            boot_changed,
            "pre/post /proc/sys/kernel/random/boot_id values must differ",
        )
    elif drill_type == "disk_backlog":
        queue_ok = (
            isinstance(peak_queue_depth, int)
            and isinstance(queue_capacity, int)
            and queue_capacity > 0
            and peak_queue_depth >= 1_000
            and peak_queue_depth < queue_capacity
            and all(
                int(after_health.get(item, {}).get("queue_depth", -1)) == 0
                for item in session.collector_ids
            )
        )
        check(
            "bounded_backlog_drained",
            queue_ok,
            f"peak={peak_queue_depth}; capacity={queue_capacity}; required_peak>=1000",
        )
    elif drill_type == "storage_restore":
        restore_ok = (
            _valid_sha256(storage_source_sha256)
            and _valid_sha256(storage_restored_sha256)
            and storage_source_sha256 == storage_restored_sha256
        )
        check(
            "storage_bundle_identity",
            restore_ok,
            "source and restored verified-bundle SHA-256 must be identical",
        )

    return PhaseOneRecoveryDrillReport(
        schema_version=1,
        drill_type=drill_type,
        qualified=all(item.passed for item in checks),
        session_id=session.session_id,
        source_commit=session.source_commit,
        operator=operator,
        started_at_utc=started_at_utc,
        completed_at_utc=completed_at_utc,
        replay_checksum=replay_checksum,
        checks=tuple(checks),
    )


def write_recovery_drill_report(
    path: Path, report: PhaseOneRecoveryDrillReport
) -> None:
    value = json.dumps(report.to_dict(), sort_keys=True, indent=2) + "\n"
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    try:
        with temp_path.open("x", encoding="utf-8", newline="\n") as handle:
            handle.write(value)
            handle.flush()
            os.fsync(handle.fileno())
        os.link(temp_path, path)
    except FileExistsError as exc:
        raise FileExistsError(
            f"drill report already exists and will not be overwritten: {path}"
        ) from exc
    finally:
        temp_path.unlink(missing_ok=True)


def _valid_before_snapshot(collector_id: str, snapshot: Mapping[str, Any]) -> bool:
    return (
        snapshot.get("collector_id") == collector_id
        and snapshot.get("status") == "running"
        and snapshot.get("connected") is True
        and int(snapshot.get("dropped_event_count", -1)) == 0
        and int(snapshot.get("sequence_uncertainty_count", -1)) == 0
        and _meaningful(snapshot.get("connection_id"))
    )


def _valid_after_snapshot(
    collector_id: str, snapshot: Mapping[str, Any], *, completed_ns: int
) -> bool:
    last_event = int(snapshot.get("last_event_receive_ts_ns") or 0)
    last_flush = int(snapshot.get("last_flush_ts_ns") or 0)
    # A post-drill capture may occur shortly after ``completed_at_utc``; its
    # event/flush must at least be inside the drill window, not historical.
    return (
        snapshot.get("collector_id") == collector_id
        and snapshot.get("status") == "running"
        and snapshot.get("connected") is True
        and int(snapshot.get("dropped_event_count", -1)) == 0
        and int(snapshot.get("sequence_uncertainty_count", -1)) == 0
        and int(snapshot.get("queue_depth", -1)) == 0
        and int(snapshot.get("events_received", 0)) > 0
        and int(snapshot.get("events_written", 0)) > 0
        and last_event > 0
        and last_flush > 0
        and last_event >= completed_ns - 60 * 1_000_000_000
        and last_flush >= completed_ns - 60 * 1_000_000_000
        and _meaningful(snapshot.get("connection_id"))
    )


def _valid_stopped_snapshot(collector_id: str, snapshot: Mapping[str, Any]) -> bool:
    return (
        snapshot.get("collector_id") == collector_id
        and snapshot.get("status") == "stopped"
        and snapshot.get("connected") is False
        and int(snapshot.get("queue_depth", -1)) == 0
        and int(snapshot.get("events_received", -1))
        == int(snapshot.get("events_written", -2))
        and int(snapshot.get("dropped_event_count", -1)) == 0
    )


def _valid_replay(report: Mapping[str, Any]) -> bool:
    books = _mapping(report.get("orderbooks"))
    tickers = _mapping(report.get("ticker_checksums"))
    return (
        int(report.get("raw_event_count", 0)) > 0
        and set(books) == set(EXPECTED_SYMBOLS)
        and set(tickers) == set(EXPECTED_SYMBOLS)
        and _valid_sha256(report.get("replay_checksum"))
        and all(
            int(_mapping(books.get(symbol)).get("bid_levels", 0)) > 0
            and int(_mapping(books.get(symbol)).get("ask_levels", 0)) > 0
            and _valid_sha256(_mapping(books.get(symbol)).get("checksum"))
            for symbol in EXPECTED_SYMBOLS
        )
    )


def _timestamp_ns(value: str) -> int:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError(f"invalid timestamp {value!r}") from exc
    if parsed.tzinfo is None:
        raise ValueError("drill timestamps must include a timezone")
    return int(parsed.timestamp() * 1_000_000_000)


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _valid_sha256(value: Any) -> bool:
    normalized = str(value)
    return bool(_SHA256.fullmatch(normalized)) and set(normalized) != {"0"}


def _meaningful(value: Any) -> bool:
    if not isinstance(value, str):
        return False
    normalized = value.strip().lower()
    return bool(normalized) and normalized not in {"replace-me", "todo", "tbd"}
