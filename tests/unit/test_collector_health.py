"""Collector health is atomic, machine-readable, and fail-closed."""

from __future__ import annotations

import json
from pathlib import Path

from src.data.collector_health import (
    AtomicHealthPublisher,
    CollectorHealth,
    evaluate_health,
)


class FakeClock:
    def __init__(self, value: int = 1_000_000_000) -> None:
        self.value = value

    def __call__(self) -> int:
        return self.value


def test_health_snapshot_tracks_events_flushes_and_uncertainty() -> None:
    clock = FakeClock()
    health = CollectorHealth(
        exchange="bybit", market_type="linear", symbols=("BTCUSDT",), wall_clock_ns=clock
    )
    health.mark_connected("connection-1")
    health.record_event(channel="trades", symbol="BTCUSDT", receive_ts_ns=10)
    health.record_flush(
        event_count=1,
        part_count=1,
        queue_depth=0,
        last_manifest_path="raw/part.manifest.json",
    )
    health.record_sequence_uncertainty("gap")

    snapshot = health.snapshot()
    assert snapshot["events_received"] == 1
    assert snapshot["events_written"] == 1
    assert snapshot["channel_counts"] == {"trades:BTCUSDT": 1}
    assert snapshot["sequence_uncertainty_count"] == 1
    assert snapshot["status"] == "sequence_uncertain"


def test_publisher_atomically_writes_json_and_prometheus(tmp_path: Path) -> None:
    clock = FakeClock()
    health = CollectorHealth(
        exchange="bybit", market_type="linear", symbols=("BTCUSDT",), wall_clock_ns=clock
    )
    health.mark_connected("connection-1")
    publisher = AtomicHealthPublisher(tmp_path / "health.json")

    publisher.publish(health.snapshot())

    payload = json.loads((tmp_path / "health.json").read_text(encoding="utf-8"))
    metrics = (tmp_path / "health.prom").read_text(encoding="utf-8")
    history_files = list((tmp_path / "history" / "health").glob("*.jsonl"))
    assert payload["connected"] is True
    assert payload["storage_total_bytes"] > 0
    assert payload["storage_available_bytes"] > 0
    assert "greenfield_collector_connected" in metrics
    assert "greenfield_collector_heartbeat_timestamp_seconds" in metrics
    assert "greenfield_collector_storage_available_bytes" in metrics
    assert len(history_files) == 1
    assert json.loads(history_files[0].read_text(encoding="utf-8"))["connected"] is True
    assert not list(tmp_path.glob("*.tmp"))


def test_health_evaluation_rejects_stale_or_lossy_collector() -> None:
    snapshot = {
        "heartbeat_ts_ns": 1,
        "status": "failed",
        "dropped_event_count": 1,
    }

    errors = evaluate_health(
        snapshot, now_ns=10_000_000_000, max_heartbeat_age_secs=1.0
    )

    assert "collector heartbeat is stale" in errors
    assert "collector status is 'failed'" in errors
    assert "collector dropped at least one raw event" in errors
