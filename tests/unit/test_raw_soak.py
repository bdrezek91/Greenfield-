"""Phase 1 soak gates require continuous, lossless health evidence."""

from __future__ import annotations

from pathlib import Path

from src.data.collector_health import AtomicHealthPublisher
from src.data.raw_soak import audit_raw_soak


def _snapshot(timestamp: int, *, dropped: int = 0) -> dict:
    return {
        "schema_version": 1,
        "exchange": "bybit",
        "market_type": "linear",
        "collector_id": "btcusdt",
        "symbols": ["BTCUSDT"],
        "status": "running",
        "heartbeat_ts_ns": timestamp,
        "connected": True,
        "events_received": 10,
        "events_written": 10,
        "parts_written": 1,
        "queue_depth": 0,
        "reconnect_count": 0,
        "sequence_uncertainty_count": 0,
        "dropped_event_count": dropped,
    }


def test_continuous_history_qualifies(tmp_path: Path) -> None:
    publisher = AtomicHealthPublisher(
        tmp_path / "health" / "bybit-linear-btcusdt.json"
    )
    for timestamp in (1_000_000_000, 6_000_000_000, 11_000_000_000):
        publisher.publish(_snapshot(timestamp))

    report = audit_raw_soak(
        tmp_path,
        collector_ids=("btcusdt",),
        start_ts_ns=1_000_000_000,
        end_ts_ns=11_000_000_000,
        required_duration_secs=10,
        maximum_heartbeat_gap_secs=5,
    )

    assert report.qualified
    assert report.collectors["btcusdt"].sample_count == 3


def test_drop_or_missing_heartbeat_disqualifies(tmp_path: Path) -> None:
    publisher = AtomicHealthPublisher(
        tmp_path / "health" / "bybit-linear-btcusdt.json"
    )
    publisher.publish(_snapshot(1_000_000_000))
    publisher.publish(_snapshot(11_000_000_000, dropped=1))

    result = audit_raw_soak(
        tmp_path,
        collector_ids=("btcusdt",),
        start_ts_ns=1_000_000_000,
        end_ts_ns=11_000_000_000,
        required_duration_secs=10,
        maximum_heartbeat_gap_secs=5,
    ).collectors["btcusdt"]

    assert not result.qualified
    assert any("heartbeat gap" in error for error in result.errors)
    assert any("dropped events" in error for error in result.errors)
