"""Build a machine-readable seven-day capacity forecast from a raw smoke run."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated, Any

import typer

from src.data.capacity_forecast import forecast_raw_capacity

app = typer.Typer(add_completion=False)


@app.command()
def forecast(
    source_commit: Annotated[
        str, typer.Option(help="Exact 40-character deployed Git commit SHA.")
    ],
    sample_data_dir: Annotated[
        Path, typer.Option(help="Sample root containing raw/ and health JSON.")
    ],
    sample_health_path: Annotated[
        Path, typer.Option(help="Final lossless collector health JSON.")
    ],
    target_data_dir: Annotated[
        Path, typer.Option(help="Mounted filesystem that will store the soak.")
    ],
    burst_multiplier: Annotated[
        float, typer.Option(help="Stress multiple applied to measured byte rate.")
    ] = 4.0,
    runtime_reserve_gib: Annotated[
        float, typer.Option(help="Hard free-space reserve excluded from capacity.")
    ] = 5.0,
    target_days: Annotated[
        float, typer.Option(help="Forecast horizon in continuous days.")
    ] = 7.0,
    minimum_sample_secs: Annotated[
        float, typer.Option(help="Minimum accepted measured sample duration.")
    ] = 10.0,
    report_path: Annotated[
        Path, typer.Option(help="Atomic JSON report output path.")
    ] = Path("reports/phase1_capacity_forecast.json"),
) -> None:
    health_bytes = sample_health_path.read_bytes()
    health = _load_health_bytes(health_bytes)
    raw_tree_sha256, raw_file_count, sample_raw_bytes = _hash_file_tree(
        sample_data_dir / "raw"
    )
    resolved_target = target_data_dir.resolve(strict=True)
    started_ns = _required_int(health, "started_ts_ns")
    final_ns = _required_int(health, "heartbeat_ts_ns")
    symbols = health.get("symbols")
    channel_counts = health.get("channel_counts")
    expected_symbols = {"BTCUSDT", "ETHUSDT", "SOLUSDT"}
    expected_streams = {
        f"{channel}:{symbol}"
        for channel in ("orderbook", "ticker", "trades")
        for symbol in expected_symbols
    }
    baseline_streams_complete = (
        isinstance(symbols, list)
        and set(symbols) == expected_symbols
        and isinstance(channel_counts, dict)
        and all(
            isinstance(channel_counts.get(stream), int)
            and channel_counts[stream] > 0
            for stream in expected_streams
        )
    )
    report = forecast_raw_capacity(
        sample_duration_secs=(final_ns - started_ns) / 1_000_000_000,
        sample_raw_bytes=sample_raw_bytes,
        generated_at_utc=datetime.now(UTC).isoformat(),
        source_commit=source_commit,
        target_data_dir=str(resolved_target),
        sample_health_sha256=hashlib.sha256(health_bytes).hexdigest(),
        sample_raw_tree_sha256=raw_tree_sha256,
        sample_raw_file_count=raw_file_count,
        events_received=_required_int(health, "events_received"),
        events_written=_required_int(health, "events_written"),
        dropped_event_count=_required_int(health, "dropped_event_count"),
        sequence_uncertainty_count=_required_int(
            health, "sequence_uncertainty_count"
        ),
        sample_finalized=(
            health.get("status") == "stopped" and health.get("connected") is False
        ),
        sample_queue_depth=_required_int(health, "queue_depth"),
        baseline_streams_complete=baseline_streams_complete,
        available_capacity_bytes=shutil.disk_usage(resolved_target).free,
        target_duration_secs=target_days * 24 * 60 * 60,
        burst_multiplier=burst_multiplier,
        runtime_reserve_bytes=int(runtime_reserve_gib * 1024**3),
        minimum_sample_duration_secs=minimum_sample_secs,
    )
    output = json.dumps(report.to_dict(), sort_keys=True, indent=2) + "\n"
    _atomic_write(report_path, output)
    typer.echo(output, nl=False)
    if not report.qualified:
        raise typer.Exit(code=1)


def _load_health_bytes(raw: bytes) -> dict[str, Any]:
    value = json.loads(raw)
    if not isinstance(value, dict):
        raise ValueError("health evidence must be a JSON object")
    return value


def _hash_file_tree(root: Path) -> tuple[str, int, int]:
    resolved_root = root.resolve(strict=True)
    if not resolved_root.is_dir():
        raise ValueError("sample raw path must be a directory")
    entries: list[dict[str, str | int]] = []
    total_bytes = 0
    for path in sorted(resolved_root.rglob("*")):
        if path.is_symlink():
            raise ValueError(f"sample raw tree cannot contain symlinks: {path}")
        if not path.is_file():
            continue
        raw = path.read_bytes()
        total_bytes += len(raw)
        entries.append(
            {
                "path": path.relative_to(resolved_root).as_posix(),
                "size_bytes": len(raw),
                "sha256": hashlib.sha256(raw).hexdigest(),
            }
        )
    if not entries:
        raise ValueError("sample raw tree contains no files")
    manifest = json.dumps(entries, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(manifest).hexdigest(), len(entries), total_bytes


def _required_int(value: dict[str, Any], key: str) -> int:
    item = value.get(key)
    if not isinstance(item, int):
        raise ValueError(f"health evidence lacks integer {key}")
    return item


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


if __name__ == "__main__":
    app()
