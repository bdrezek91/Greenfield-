from __future__ import annotations

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from scripts.forecast_raw_venue_capacity import app as capacity_app
from src.data.raw_venue_smoke import (
    evaluate_raw_venue_smoke,
    load_raw_venue_smoke_report,
    write_raw_venue_smoke_report,
)

COMMIT = "a" * 40
SHA = "b" * 64
SYMBOLS = ("BTC-USDT-SWAP", "ETH-USDT-SWAP", "SOL-USDT-SWAP")


def _sample(tmp_path: Path, *, omit_stream: str | None = None) -> tuple[Path, Path]:
    raw = tmp_path / "raw" / "okx"
    raw.mkdir(parents=True)
    (raw / "part.parquet").write_bytes(b"bounded-okx-sample")
    channels = {
        f"{channel}:{symbol}": 1
        for channel in ("orderbook", "trades", "ticker")
        for symbol in SYMBOLS
        if f"{channel}:{symbol}" != omit_stream
    }
    health = tmp_path / "health" / "okx-swap-smoke-okx.json"
    health.parent.mkdir()
    health.write_text(
        json.dumps(
            {
                "exchange": "okx",
                "market_type": "swap",
                "collector_id": "smoke-okx",
                "symbols": list(SYMBOLS),
                "started_ts_ns": 1_000_000_000,
                "heartbeat_ts_ns": 121_000_000_000,
                "events_received": 90,
                "events_written": 90,
                "dropped_event_count": 0,
                "sequence_uncertainty_count": 0,
                "queue_depth": 0,
                "status": "stopped",
                "connected": False,
                "channel_counts": channels,
            }
        ),
        encoding="utf-8",
    )
    return tmp_path, health


def _report(tmp_path: Path, *, omit_stream: str | None = None):
    sample, health = _sample(tmp_path, omit_stream=omit_stream)
    return evaluate_raw_venue_smoke(
        venue="okx",
        source_commit=COMMIT,
        venue_preflight_report_sha256=SHA,
        sample_root=sample,
        health_path=health,
        collector_id="smoke-okx",
        minimum_duration_secs=120,
        maximum_duration_secs=120,
    )


def test_qualified_smoke_is_immutable_and_reloadable(tmp_path: Path) -> None:
    report = _report(tmp_path)
    path = tmp_path / "smoke.json"

    assert report.qualified
    assert report.sample_raw_file_count == 1
    assert report.sample_raw_bytes > 0
    write_raw_venue_smoke_report(path, report)
    assert load_raw_venue_smoke_report(path) == report
    with pytest.raises(FileExistsError, match="will not be overwritten"):
        write_raw_venue_smoke_report(path, report)


def test_missing_baseline_stream_fails_closed(tmp_path: Path) -> None:
    report = _report(tmp_path, omit_stream="trades:SOL-USDT-SWAP")

    assert not report.qualified
    assert not report.checks["baseline_streams_complete"]


def test_capacity_cli_binds_smoke_venue_and_namespace(tmp_path: Path) -> None:
    smoke = _report(tmp_path / "sample")
    smoke_path = tmp_path / "smoke.json"
    write_raw_venue_smoke_report(smoke_path, smoke)
    target = tmp_path / "target"
    target.mkdir()
    capacity_path = tmp_path / "capacity.json"

    result = CliRunner().invoke(
        capacity_app,
        [
            "--smoke-report-path",
            str(smoke_path),
            "--target-data-dir",
            str(target),
            "--report-path",
            str(capacity_path),
        ],
    )

    assert result.exit_code == 0, result.output
    value = json.loads(capacity_path.read_text(encoding="utf-8"))
    assert value["schema_version"] == 2
    assert value["venue"] == "okx"
    assert value["health_namespace"] == "okx-swap"
    assert value["sample_collector_ids"] == ["smoke-okx"]
    assert len(value["smoke_report_sha256"]) == 64
