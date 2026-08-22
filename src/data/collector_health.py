"""Thread-safe health state and atomic observability files for collectors."""

from __future__ import annotations

import json
import os
import shutil
import threading
import time
import uuid
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


class CollectorHealth:
    def __init__(
        self,
        *,
        exchange: str,
        market_type: str,
        symbols: tuple[str, ...],
        collector_id: str = "all",
        wall_clock_ns: Callable[[], int] = time.time_ns,
    ) -> None:
        self._lock = threading.Lock()
        self._wall_clock_ns = wall_clock_ns
        started = wall_clock_ns()
        self._state: dict[str, Any] = {
            "schema_version": 1,
            "exchange": exchange,
            "market_type": market_type,
            "collector_id": collector_id,
            "symbols": list(symbols),
            "status": "starting",
            "started_ts_ns": started,
            "heartbeat_ts_ns": started,
            "connected": False,
            "connection_id": None,
            "connection_started_ts_ns": None,
            "last_event_receive_ts_ns": None,
            "last_flush_ts_ns": None,
            "last_manifest_path": None,
            "last_error": None,
            "channel_counts": {},
            "events_received": 0,
            "events_written": 0,
            "parts_written": 0,
            "queue_depth": 0,
            "reconnect_count": 0,
            "sequence_uncertainty_count": 0,
            "dropped_event_count": 0,
        }

    def mark_connected(self, connection_id: str) -> None:
        with self._lock:
            now = self._wall_clock_ns()
            self._state.update(
                status="running",
                connected=True,
                connection_id=connection_id,
                connection_started_ts_ns=now,
                heartbeat_ts_ns=now,
                last_error=None,
            )

    def mark_disconnected(self, reason: str | None = None) -> None:
        with self._lock:
            self._state["connected"] = False
            self._state["status"] = "reconnecting"
            self._state["heartbeat_ts_ns"] = self._wall_clock_ns()
            if reason:
                self._state["last_error"] = reason

    def record_event(self, *, channel: str, symbol: str, receive_ts_ns: int) -> None:
        with self._lock:
            key = f"{channel}:{symbol}"
            counts = self._state["channel_counts"]
            counts[key] = counts.get(key, 0) + 1
            self._state["events_received"] += 1
            self._state["last_event_receive_ts_ns"] = receive_ts_ns

    def record_flush(
        self,
        *,
        event_count: int,
        part_count: int,
        queue_depth: int,
        last_manifest_path: str | None,
    ) -> None:
        with self._lock:
            self._state["events_written"] += event_count
            self._state["parts_written"] += part_count
            self._state["queue_depth"] = queue_depth
            self._state["last_flush_ts_ns"] = self._wall_clock_ns()
            self._state["last_manifest_path"] = last_manifest_path

    def record_reconnect(self) -> None:
        with self._lock:
            self._state["reconnect_count"] += 1

    def record_sequence_uncertainty(self, reason: str) -> None:
        with self._lock:
            self._state["sequence_uncertainty_count"] += 1
            self._state["status"] = "sequence_uncertain"
            self._state["last_error"] = reason
            self._state["heartbeat_ts_ns"] = self._wall_clock_ns()

    def record_drop(self, reason: str) -> None:
        with self._lock:
            self._state["dropped_event_count"] += 1
            self._state["status"] = "failed"
            self._state["last_error"] = reason
            self._state["heartbeat_ts_ns"] = self._wall_clock_ns()

    def record_error(self, reason: str) -> None:
        with self._lock:
            self._state["last_error"] = reason
            self._state["heartbeat_ts_ns"] = self._wall_clock_ns()

    def mark_stopping(self) -> None:
        with self._lock:
            self._state["status"] = "stopping"
            self._state["heartbeat_ts_ns"] = self._wall_clock_ns()

    def mark_stopped(self, *, failed: bool = False) -> None:
        with self._lock:
            self._state["status"] = "failed" if failed else "stopped"
            self._state["connected"] = False
            self._state["queue_depth"] = 0
            self._state["heartbeat_ts_ns"] = self._wall_clock_ns()

    def snapshot(self, *, queue_depth: int | None = None) -> dict[str, Any]:
        with self._lock:
            value = dict(self._state)
            value["channel_counts"] = dict(self._state["channel_counts"])
            value["symbols"] = list(self._state["symbols"])
            value["heartbeat_ts_ns"] = self._wall_clock_ns()
            if queue_depth is not None:
                value["queue_depth"] = queue_depth
            return value


class AtomicHealthPublisher:
    def __init__(self, health_path: Path) -> None:
        self.health_path = Path(health_path)
        self.metrics_path = self.health_path.with_suffix(".prom")
        self.history_root = (
            self.health_path.parent / "history" / self.health_path.stem
        )
        self._lock = threading.Lock()

    def publish(self, snapshot: dict[str, Any]) -> None:
        with self._lock:
            self.health_path.parent.mkdir(parents=True, exist_ok=True)
            usage = shutil.disk_usage(self.health_path.parent)
            document = dict(snapshot)
            document.update(
                storage_total_bytes=usage.total,
                storage_used_bytes=usage.used,
                storage_available_bytes=usage.free,
            )
            _atomic_write(
                self.health_path,
                json.dumps(document, sort_keys=True, indent=2) + "\n",
            )
            _atomic_write(self.metrics_path, _prometheus_metrics(document))
            heartbeat_ns = int(document["heartbeat_ts_ns"])
            utc_date = datetime.fromtimestamp(
                heartbeat_ns // 1_000_000_000, tz=UTC
            ).date().isoformat()
            _append_fsynced_jsonl(
                self.history_root / f"{utc_date}.jsonl",
                json.dumps(document, sort_keys=True, separators=(",", ":")) + "\n",
            )


def evaluate_health(
    snapshot: dict[str, Any], *, now_ns: int, max_heartbeat_age_secs: float
) -> list[str]:
    errors = []
    heartbeat = snapshot.get("heartbeat_ts_ns")
    if not isinstance(heartbeat, int):
        errors.append("missing heartbeat_ts_ns")
    elif now_ns - heartbeat > max_heartbeat_age_secs * 1_000_000_000:
        errors.append("collector heartbeat is stale")
    if snapshot.get("status") not in {"running", "reconnecting"}:
        errors.append(f"collector status is {snapshot.get('status')!r}")
    if int(snapshot.get("dropped_event_count", 0)) > 0:
        errors.append("collector dropped at least one raw event")
    return errors


def _prometheus_metrics(snapshot: dict[str, Any]) -> str:
    labels = (
        f'exchange="{snapshot["exchange"]}",'
        f'market_type="{snapshot["market_type"]}",'
        f'collector_id="{snapshot["collector_id"]}"'
    )
    connected = 1 if snapshot.get("connected") else 0
    lines = [
        "# TYPE greenfield_collector_connected gauge",
        f"greenfield_collector_connected{{{labels}}} {connected}",
        "# TYPE greenfield_collector_status gauge",
        (
            "greenfield_collector_status{"
            f'{labels},status="{snapshot["status"]}"'
            "} 1"
        ),
    ]
    for name in (
        "events_received",
        "events_written",
        "parts_written",
        "queue_depth",
        "reconnect_count",
        "sequence_uncertainty_count",
        "dropped_event_count",
        "heartbeat_ts_ns",
        "last_event_receive_ts_ns",
        "last_flush_ts_ns",
        "storage_total_bytes",
        "storage_used_bytes",
        "storage_available_bytes",
    ):
        value = snapshot.get(name)
        if value is None:
            continue
        lines.extend(
            [
                f"# TYPE greenfield_collector_{name} gauge",
                f"greenfield_collector_{name}{{{labels}}} {value}",
            ]
        )
    for source_name, metric_name in (
        ("heartbeat_ts_ns", "heartbeat_timestamp_seconds"),
        ("last_event_receive_ts_ns", "last_event_receive_timestamp_seconds"),
        ("last_flush_ts_ns", "last_flush_timestamp_seconds"),
    ):
        value = snapshot.get(source_name)
        if value is None:
            continue
        lines.extend(
            [
                f"# TYPE greenfield_collector_{metric_name} gauge",
                (
                    f"greenfield_collector_{metric_name}{{{labels}}} "
                    f"{int(value) / 1_000_000_000}"
                ),
            ]
        )
    return "\n".join(lines) + "\n"


def _atomic_write(path: Path, value: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    try:
        with temp_path.open("w", encoding="utf-8", newline="\n") as handle:
            handle.write(value)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_path, path)
    finally:
        temp_path.unlink(missing_ok=True)


def _append_fsynced_jsonl(path: Path, value: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8", newline="\n") as handle:
        handle.write(value)
        handle.flush()
        os.fsync(handle.fileno())
