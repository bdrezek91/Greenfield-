from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from src.execution.demo_scalp_health import DemoScalpHealthPublisher


def test_health_publishes_atomic_json_and_prometheus(tmp_path: Path) -> None:
    path = tmp_path / "health.json"
    DemoScalpHealthPublisher(path).publish(
        {
            "timestamp_utc": datetime(2026, 8, 24, tzinfo=UTC).isoformat(),
            "status": "OPEN",
            "trade_id": "demo-1",
            "operator_forced": True,
        }
    )
    assert json.loads(path.read_text(encoding="utf-8"))["status"] == "OPEN"
    metrics = path.with_suffix(".prom").read_text(encoding="utf-8")
    assert 'greenfield_demo_scalp_status{status="OPEN"} 1' in metrics
    assert "greenfield_demo_scalp_operator_forced 1" in metrics
    assert "greenfield_demo_scalp_active_trade 1" in metrics


def test_unknown_status_is_rejected_without_overwriting(tmp_path: Path) -> None:
    path = tmp_path / "health.json"
    path.write_text("old\n", encoding="utf-8")
    with pytest.raises(ValueError, match="unknown"):
        DemoScalpHealthPublisher(path).publish(
            {"timestamp_utc": datetime.now(UTC).isoformat(), "status": "MAYBE"}
        )
    assert path.read_text(encoding="utf-8") == "old\n"
