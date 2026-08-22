"""Recovery drill reports require objective state transitions and replay."""

from __future__ import annotations

from pathlib import Path

import pytest

from src.data.phase1_recovery_drill import (
    DRILL_TYPES,
    evaluate_phase1_recovery_drill,
    write_recovery_drill_report,
)
from src.data.raw_soak_session import RawSoakSession

SHA = "a" * 64
COMMIT = "b" * 40
START_NS = 1_800_000_000_000_000_000
START = "2027-01-15T08:00:00+00:00"
END = "2027-01-15T08:01:00+00:00"


def _session() -> RawSoakSession:
    return RawSoakSession(
        schema_version=2,
        session_id="phase1-session",
        started_at_utc="2027-01-15T07:59:00+00:00",
        start_ts_ns=START_NS - 60_000_000_000,
        source_commit=COMMIT,
        minimum_duration_secs=604_800,
        collector_ids=("btcusdt", "ethusdt", "solusdt"),
        preflight_report_path="preflight.json",
        preflight_report_sha256=SHA,
        capacity_forecast_report_path="capacity.json",
        capacity_forecast_report_sha256=SHA,
        config_sha256={"compose.yml": SHA},
    )


def _health(connection_suffix: str, *, status: str = "running") -> dict[str, dict]:
    values = {}
    timestamp = START_NS + 60_000_000_000
    for collector in _session().collector_ids:
        values[collector] = {
            "collector_id": collector,
            "status": status,
            "connected": status == "running",
            "connection_id": f"{collector}-{connection_suffix}",
            "events_received": 100,
            "events_written": 100,
            "queue_depth": 0,
            "dropped_event_count": 0,
            "sequence_uncertainty_count": 0,
            "last_event_receive_ts_ns": timestamp,
            "last_flush_ts_ns": timestamp,
        }
    return values


def _replay() -> dict:
    books = {
        symbol: {"bid_levels": 50, "ask_levels": 50, "checksum": SHA}
        for symbol in ("BTCUSDT", "ETHUSDT", "SOLUSDT")
    }
    return {
        "raw_event_count": 10_000,
        "orderbooks": books,
        "ticker_checksums": {symbol: SHA for symbol in books},
        "replay_checksum": SHA,
    }


def _evaluate(drill_type: str, **specific):
    return evaluate_phase1_recovery_drill(
        drill_type=drill_type,
        session=_session(),
        before_health=_health("before"),
        after_health=_health("after"),
        replay_report=_replay(),
        operator="operator-a",
        started_at_utc=START,
        completed_at_utc=END,
        **specific,
    )


def test_graceful_sigterm_requires_drained_stopped_snapshot(tmp_path: Path) -> None:
    report = _evaluate(
        "graceful_sigterm", transition_health=_health("stopped", status="stopped")
    )
    assert report.qualified
    output = tmp_path / "graceful.json"
    write_recovery_drill_report(output, report)
    assert '"qualified": true' in output.read_text(encoding="utf-8")
    with pytest.raises(FileExistsError, match="will not be overwritten"):
        write_recovery_drill_report(output, report)


def test_restart_requires_new_connections() -> None:
    report = evaluate_phase1_recovery_drill(
        drill_type="process_restart",
        session=_session(),
        before_health=_health("same"),
        after_health=_health("same"),
        replay_report=_replay(),
        operator="operator-a",
        started_at_utc=START,
        completed_at_utc=END,
    )
    assert not report.qualified
    assert not next(item for item in report.checks if item.name == "new_connections").passed


def test_vps_reboot_requires_changed_boot_id() -> None:
    assert _evaluate(
        "vps_reboot", boot_id_before="boot-a", boot_id_after="boot-b"
    ).qualified
    assert not _evaluate(
        "vps_reboot", boot_id_before="boot-a", boot_id_after="boot-a"
    ).qualified


def test_disk_backlog_must_be_measurable_bounded_and_drained() -> None:
    assert _evaluate(
        "disk_backlog", peak_queue_depth=10_000, queue_capacity=100_000
    ).qualified
    assert not _evaluate(
        "disk_backlog", peak_queue_depth=100_000, queue_capacity=100_000
    ).qualified


def test_storage_restore_requires_identical_nonzero_bundle_hash() -> None:
    assert _evaluate(
        "storage_restore", storage_source_sha256=SHA, storage_restored_sha256=SHA
    ).qualified
    assert not _evaluate(
        "storage_restore",
        storage_source_sha256=SHA,
        storage_restored_sha256="c" * 64,
    ).qualified


@pytest.mark.parametrize("drill_type", DRILL_TYPES)
def test_common_loss_or_replay_failure_disqualifies_every_drill(drill_type: str) -> None:
    after = _health("after")
    after["btcusdt"]["dropped_event_count"] = 1
    specific = {
        "transition_health": _health("stopped", status="stopped"),
        "boot_id_before": "boot-a",
        "boot_id_after": "boot-b",
        "peak_queue_depth": 10_000,
        "queue_capacity": 100_000,
        "storage_source_sha256": SHA,
        "storage_restored_sha256": SHA,
    }
    report = evaluate_phase1_recovery_drill(
        drill_type=drill_type,
        session=_session(),
        before_health=_health("before"),
        after_health=after,
        replay_report=_replay(),
        operator="operator-a",
        started_at_utc=START,
        completed_at_utc=END,
        **specific,
    )
    assert not report.qualified
