"""Raw capacity forecasts must fail closed on loss or insufficient headroom."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from scripts.forecast_phase1_capacity import app
from src.data.capacity_forecast import forecast_raw_capacity

GIB = 1024**3
COMMIT = "a" * 40
SHA = "b" * 64


def _forecast(**overrides: object):
    values = {
        "sample_duration_secs": 20.0,
        "sample_raw_bytes": 1 * GIB,
        "generated_at_utc": "2026-08-22T12:00:00+00:00",
        "source_commit": COMMIT,
        "target_data_dir": "/data",
        "sample_health_sha256": SHA,
        "sample_raw_tree_sha256": SHA,
        "sample_raw_file_count": 10,
        "events_received": 1_000,
        "events_written": 1_000,
        "dropped_event_count": 0,
        "sequence_uncertainty_count": 0,
        "sample_finalized": True,
        "sample_queue_depth": 0,
        "baseline_streams_complete": True,
        "available_capacity_bytes": 90 * GIB,
        "target_duration_secs": 100.0,
        "burst_multiplier": 4.0,
        "runtime_reserve_bytes": 5 * GIB,
        "minimum_sample_duration_secs": 10.0,
    }
    values.update(overrides)
    return forecast_raw_capacity(**values)  # type: ignore[arg-type]


def test_lossless_stressed_projection_with_headroom_qualifies() -> None:
    report = _forecast()

    assert report.qualified
    assert report.base_projected_bytes == 5 * GIB
    assert report.stressed_projected_bytes == 20 * GIB
    assert report.required_capacity_bytes == 25 * GIB
    assert report.projected_headroom_bytes == 65 * GIB
    assert all(report.checks.values())


@pytest.mark.parametrize(
    ("override", "failed_check"),
    [
        ({"sample_duration_secs": 9.0}, "minimum_sample_duration"),
        ({"events_written": 999}, "sample_fully_flushed"),
        ({"sample_finalized": False}, "sample_finalized"),
        ({"sample_queue_depth": 1}, "sample_queue_drained"),
        ({"baseline_streams_complete": False}, "baseline_streams_complete"),
        ({"dropped_event_count": 1}, "sample_zero_drops"),
        ({"sequence_uncertainty_count": 1}, "sample_zero_sequence_uncertainty"),
        (
            {"available_capacity_bytes": 24 * GIB},
            "stressed_projection_fits_with_reserve",
        ),
    ],
)
def test_forecast_fails_closed(override: dict[str, object], failed_check: str) -> None:
    report = _forecast(**override)

    assert not report.qualified
    assert not report.checks[failed_check]


def test_nonpositive_inputs_are_rejected() -> None:
    with pytest.raises(ValueError, match="must be positive"):
        _forecast(burst_multiplier=0.0)


def test_venue_capacity_forecast_carries_exact_sample_identity() -> None:
    report = _forecast(
        venue="okx",
        health_namespace="okx-swap",
        sample_collector_ids=("smoke-okx",),
        smoke_report_sha256=SHA,
    )

    assert report.schema_version == 2
    assert report.venue == "okx"
    assert report.health_namespace == "okx-swap"
    assert report.sample_collector_ids == ("smoke-okx",)


@pytest.mark.parametrize(
    "overrides",
    [
        {"venue": "okx"},
        {"health_namespace": "okx-swap"},
        {
            "venue": "okx",
            "health_namespace": "okx-swap",
            "sample_collector_ids": (),
            "smoke_report_sha256": SHA,
        },
    ],
)
def test_incomplete_venue_capacity_identity_is_rejected(
    overrides: dict[str, object],
) -> None:
    with pytest.raises(ValueError, match="venue|sample_collector_ids"):
        _forecast(**overrides)


def _write_cli_fixture(root: Path, *, omit_stream: str | None = None) -> Path:
    raw_dir = root / "raw"
    raw_dir.mkdir()
    (raw_dir / "part.parquet").write_bytes(b"measured-raw-bytes")
    streams = {
        f"{channel}:{symbol}": 1
        for channel in ("orderbook", "ticker", "trades")
        for symbol in ("BTCUSDT", "ETHUSDT", "SOLUSDT")
        if f"{channel}:{symbol}" != omit_stream
    }
    health_path = root / "health.json"
    health_path.write_text(
        json.dumps(
            {
                "started_ts_ns": 1_000_000_000,
                "heartbeat_ts_ns": 21_000_000_000,
                "events_received": 9,
                "events_written": 9,
                "dropped_event_count": 0,
                "sequence_uncertainty_count": 0,
                "queue_depth": 0,
                "status": "stopped",
                "connected": False,
                "symbols": ["BTCUSDT", "ETHUSDT", "SOLUSDT"],
                "channel_counts": streams,
            }
        ),
        encoding="utf-8",
    )
    return health_path


def test_cli_writes_qualified_atomic_report(tmp_path: Path) -> None:
    health_path = _write_cli_fixture(tmp_path)
    report_path = tmp_path / "report.json"

    result = CliRunner().invoke(
        app,
        [
            "--sample-data-dir",
            str(tmp_path),
            "--source-commit",
            COMMIT,
            "--sample-health-path",
            str(health_path),
            "--target-data-dir",
            str(tmp_path),
            "--report-path",
            str(report_path),
        ],
    )

    assert result.exit_code == 0, result.output
    report = json.loads(report_path.read_text(encoding="utf-8"))
    assert report["qualified"] is True
    assert report["checks"]["baseline_streams_complete"] is True


def test_cli_fails_closed_when_a_baseline_stream_is_missing(tmp_path: Path) -> None:
    health_path = _write_cli_fixture(tmp_path, omit_stream="trades:SOLUSDT")

    result = CliRunner().invoke(
        app,
        [
            "--sample-data-dir",
            str(tmp_path),
            "--source-commit",
            COMMIT,
            "--sample-health-path",
            str(health_path),
            "--target-data-dir",
            str(tmp_path),
            "--report-path",
            str(tmp_path / "report.json"),
        ],
    )

    assert result.exit_code == 1
