"""Audit the continuous health evidence required by Greenfield v2 Phase 1."""

from __future__ import annotations

import json
import os
import time
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Annotated

import typer

from src.data.raw_soak import audit_raw_soak
from src.data.raw_soak_session import file_sha256, load_raw_soak_session

app = typer.Typer(add_completion=False)


@app.command()
def audit(
    data_dir: Annotated[
        Path | None, typer.Option(help="Defaults to DATA_DIR or ./data.")
    ] = None,
    days: Annotated[float, typer.Option(help="Required continuous window in days.")] = 7.0,
    max_gap_secs: Annotated[
        float, typer.Option(help="Maximum allowed health heartbeat gap.")
    ] = 30.0,
    report_path: Annotated[
        Path, typer.Option(help="Atomic JSON evidence report path.")
    ] = Path("reports/raw_collector_soak.json"),
    session_path: Annotated[
        Path | None,
        typer.Option(help="Immutable soak marker; recommended for Phase 1 acceptance."),
    ] = None,
) -> None:
    resolved_data_dir = Path(data_dir or os.environ.get("DATA_DIR", "./data"))
    end_ns = time.time_ns()
    session = load_raw_soak_session(session_path) if session_path is not None else None
    if session is None:
        end = datetime.fromtimestamp(end_ns / 1_000_000_000, tz=UTC)
        start = end - timedelta(days=days)
        start_ns = int(start.timestamp() * 1_000_000_000)
        required_duration_secs = days * 24 * 60 * 60
        collector_ids: tuple[str, ...] = ("btcusdt", "ethusdt", "solusdt")
        session_id = None
        source_commit = None
        session_sha256 = None
    else:
        assert session_path is not None
        start_ns = session.start_ts_ns
        required_duration_secs = session.minimum_duration_secs
        collector_ids = session.collector_ids
        session_id = session.session_id
        source_commit = session.source_commit
        session_sha256 = file_sha256(session_path)
    report = audit_raw_soak(
        resolved_data_dir,
        collector_ids=collector_ids,
        start_ts_ns=start_ns,
        end_ts_ns=end_ns,
        required_duration_secs=required_duration_secs,
        maximum_heartbeat_gap_secs=max_gap_secs,
        session_id=session_id,
        source_commit=source_commit,
        session_manifest_sha256=session_sha256,
    )
    output = json.dumps(report.to_dict(), sort_keys=True, indent=2) + "\n"
    _atomic_write(report_path, output)
    typer.echo(output, nl=False)
    if not report.qualified:
        raise typer.Exit(code=1)


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
