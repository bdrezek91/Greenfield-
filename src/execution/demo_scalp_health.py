"""Atomic JSON and Prometheus health for the Bybit Demo scalper."""

from __future__ import annotations

import json
import os
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

STATUSES = (
    "WAIT",
    "OPEN",
    "ENTRY_SUBMITTED",
    "EXIT_SUBMITTED",
    "CLOSED",
    "SAFETY_HOLD",
    "ERROR",
)


class DemoScalpHealthPublisher:
    def __init__(self, path: Path) -> None:
        self.path = Path(path)
        self.metrics_path = self.path.with_suffix(".prom")

    def publish(self, payload: dict[str, Any]) -> None:
        status = str(payload.get("status", ""))
        if status not in STATUSES:
            raise ValueError("unknown Demo scalp health status")
        timestamp = datetime.fromisoformat(str(payload["timestamp_utc"]))
        if timestamp.tzinfo is None:
            raise ValueError("Demo scalp health timestamp must be timezone-aware")
        document = dict(payload)
        document["timestamp_utc"] = timestamp.astimezone(UTC).isoformat()
        _atomic_write(self.path, json.dumps(document, sort_keys=True) + "\n")
        lines = [
            "# HELP greenfield_demo_scalp_heartbeat_timestamp_seconds "
            "Last successful cycle timestamp.",
            "# TYPE greenfield_demo_scalp_heartbeat_timestamp_seconds gauge",
            f"greenfield_demo_scalp_heartbeat_timestamp_seconds {timestamp.timestamp():.6f}",
            "# HELP greenfield_demo_scalp_status Current lifecycle status.",
            "# TYPE greenfield_demo_scalp_status gauge",
        ]
        lines.extend(
            f'greenfield_demo_scalp_status{{status="{item}"}} {int(item == status)}'
            for item in STATUSES
        )
        lines.extend(
            (
                "# HELP greenfield_demo_scalp_operator_forced "
                "Whether the cycle was operator-forced.",
                "# TYPE greenfield_demo_scalp_operator_forced gauge",
                "greenfield_demo_scalp_operator_forced "
                f"{int(bool(document.get('operator_forced')))}",
                "# HELP greenfield_demo_scalp_active_trade Whether a durable trade is active.",
                "# TYPE greenfield_demo_scalp_active_trade gauge",
                f"greenfield_demo_scalp_active_trade {int(bool(document.get('trade_id')))}",
            )
        )
        _atomic_write(self.metrics_path, "\n".join(lines) + "\n")


def _atomic_write(path: Path, value: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(value)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
        if os.name == "posix":
            directory = os.open(path.parent, os.O_RDONLY)
            try:
                os.fsync(directory)
            finally:
                os.close(directory)
    finally:
        temporary.unlink(missing_ok=True)
