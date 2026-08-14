from __future__ import annotations

from datetime import UTC, datetime, timedelta

from src.execution.heartbeat import HeartbeatMonitor


class TestHeartbeatMonitor:
    def test_stale_before_any_record(self) -> None:
        monitor = HeartbeatMonitor(max_gap_seconds=60)
        assert monitor.is_stale(datetime(2024, 1, 1, tzinfo=UTC)) is True
        assert monitor.seconds_since_last(datetime(2024, 1, 1, tzinfo=UTC)) is None

    def test_not_stale_immediately_after_record(self) -> None:
        monitor = HeartbeatMonitor(max_gap_seconds=60)
        now = datetime(2024, 1, 1, tzinfo=UTC)
        monitor.record(now)
        assert monitor.is_stale(now) is False
        assert monitor.seconds_since_last(now) == 0.0

    def test_stale_after_gap_exceeds_threshold(self) -> None:
        monitor = HeartbeatMonitor(max_gap_seconds=60)
        t0 = datetime(2024, 1, 1, tzinfo=UTC)
        monitor.record(t0)
        assert monitor.is_stale(t0 + timedelta(seconds=61)) is True
        assert monitor.is_stale(t0 + timedelta(seconds=59)) is False

    def test_boundary_is_not_stale(self) -> None:
        monitor = HeartbeatMonitor(max_gap_seconds=60)
        t0 = datetime(2024, 1, 1, tzinfo=UTC)
        monitor.record(t0)
        assert monitor.is_stale(t0 + timedelta(seconds=60)) is False

    def test_record_resets_the_clock(self) -> None:
        monitor = HeartbeatMonitor(max_gap_seconds=60)
        t0 = datetime(2024, 1, 1, tzinfo=UTC)
        monitor.record(t0)
        t1 = t0 + timedelta(seconds=30)
        monitor.record(t1)
        assert monitor.is_stale(t1 + timedelta(seconds=45)) is False
        assert monitor.last_seen == t1
