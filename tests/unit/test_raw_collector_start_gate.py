"""Raw collectors cannot start outside their exact immutable soak session."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from src.data.raw_collector_start_gate import validate_raw_collector_start

SESSION = "phase1-test-session"
COMMIT = "b" * 40
NOW_NS = 1_800_000_000_000_000_000


def _write_marker(data_dir: Path, config: Path) -> Path:
    marker = data_dir / "health" / "soak_sessions" / f"{SESSION}.json"
    marker.parent.mkdir(parents=True)
    value = {
        "schema_version": 2,
        "session_id": SESSION,
        "started_at_utc": datetime.fromtimestamp(
            NOW_NS / 1_000_000_000, tz=UTC
        ).isoformat(),
        "start_ts_ns": NOW_NS,
        "source_commit": COMMIT,
        "minimum_duration_secs": 7 * 24 * 60 * 60,
        "collector_ids": ["btcusdt", "ethusdt", "solusdt"],
        "preflight_report_path": "/evidence/preflight.json",
        "preflight_report_sha256": "a" * 64,
        "capacity_forecast_report_path": "/evidence/capacity.json",
        "capacity_forecast_report_sha256": "c" * 64,
        "config_sha256": {
            config.name: hashlib.sha256(config.read_bytes()).hexdigest(),
        },
    }
    marker.write_text(json.dumps(value), encoding="utf-8")
    return marker


def test_start_gate_binds_collector_commit_marker_and_config(tmp_path: Path) -> None:
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    config = tmp_path / "raw_collectors.yaml"
    config.write_text("schema_version: 1\n", encoding="utf-8")
    marker = _write_marker(data_dir, config)

    binding = validate_raw_collector_start(
        data_dir=data_dir,
        session_id=SESSION,
        deployed_commit=COMMIT,
        collector_id="btcusdt",
        config_paths=(config,),
        now_ns=NOW_NS + 1,
    )

    assert binding.marker_path == marker.resolve()
    assert binding.session_id == SESSION
    assert binding.source_commit == COMMIT


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("session_id", "", "SOAK_ID"),
        ("session_id", "../escape", "SOAK_ID"),
        ("deployed_commit", "", "DEPLOY_COMMIT"),
        ("deployed_commit", "c" * 40, "commit does not match"),
        ("collector_id", "xrpusdt", "not authorized"),
    ],
)
def test_start_gate_rejects_unbound_identity(
    tmp_path: Path, field: str, value: str, message: str
) -> None:
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    config = tmp_path / "raw_collectors.yaml"
    config.write_text("schema_version: 1\n", encoding="utf-8")
    _write_marker(data_dir, config)
    session_id = value if field == "session_id" else SESSION
    deployed_commit = value if field == "deployed_commit" else COMMIT
    collector_id = value if field == "collector_id" else "btcusdt"

    with pytest.raises((OSError, ValueError), match=message):
        validate_raw_collector_start(
            data_dir=data_dir,
            session_id=session_id,
            deployed_commit=deployed_commit,
            collector_id=collector_id,
            config_paths=(config,),
            now_ns=NOW_NS + 1,
        )


def test_start_gate_rejects_config_changed_after_marker(tmp_path: Path) -> None:
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    config = tmp_path / "raw_collectors.yaml"
    config.write_text("schema_version: 1\n", encoding="utf-8")
    _write_marker(data_dir, config)
    config.write_text("schema_version: 2\n", encoding="utf-8")

    with pytest.raises(ValueError, match="changed after soak marker"):
        validate_raw_collector_start(
            data_dir=data_dir,
            session_id=SESSION,
            deployed_commit=COMMIT,
            collector_id="btcusdt",
            config_paths=(config,),
            now_ns=NOW_NS + 1,
        )
