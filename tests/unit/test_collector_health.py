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
    assert "greenfield_collector_storage_runtime_minimum_free_bytes" in metrics
    assert len(history_files) == 1
    assert json.loads(history_files[0].read_text(encoding="utf-8"))["connected"] is True
    assert not list(tmp_path.glob("*.tmp"))


def test_sequence_continuity_verified_defaults_true() -> None:
    health = CollectorHealth(exchange="bybit", market_type="linear", symbols=("BTCUSDT",))
    assert health.snapshot()["sequence_continuity_verified"] is True


def test_sequence_continuity_unverified_is_visible_in_json_and_prometheus(
    tmp_path: Path,
) -> None:
    health = CollectorHealth(
        exchange="coinbase",
        market_type="spot",
        symbols=("BTC-USD",),
        sequence_continuity_verified=False,
    )
    publisher = AtomicHealthPublisher(tmp_path / "health.json")

    publisher.publish(health.snapshot())

    payload = json.loads((tmp_path / "health.json").read_text(encoding="utf-8"))
    assert payload["sequence_continuity_verified"] is False
    metrics = (tmp_path / "health.prom").read_text(encoding="utf-8")
    metric_line = next(
        line
        for line in metrics.splitlines()
        if line.startswith("greenfield_collector_sequence_continuity_verified{")
    )
    assert metric_line.endswith(" 0")


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


def test_health_evaluation_rejects_breached_storage_reserve() -> None:
    snapshot = {
        "heartbeat_ts_ns": 10_000_000_000,
        "status": "running",
        "dropped_event_count": 0,
        "storage_available_bytes": 4 * 1024**3,
        "storage_runtime_minimum_free_bytes": 5 * 1024**3,
    }

    errors = evaluate_health(
        snapshot, now_ns=10_000_000_000, max_heartbeat_age_secs=1.0
    )

    assert errors == ["collector storage reserve is breached"]
