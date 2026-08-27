"""Verify manifests and deterministically replay captured Bybit raw data."""

from __future__ import annotations

import json
import os
import uuid
from pathlib import Path
from typing import Annotated

import typer

from src.data.bybit_replay import replay_bybit_stream
from src.data.raw_store import iter_raw_events

app = typer.Typer(add_completion=False)


@app.command()
def replay(
    data_dir: Annotated[Path, typer.Option(help="Greenfield data root.")] = Path(
        "data"
    ),
    symbol: Annotated[
        str | None, typer.Option(help="Optional single-symbol filter.")
    ] = None,
    utc_date: Annotated[
        str | None,
        typer.Option(
            "--utc-date",
            help=(
                "Optional single UTC date filter (YYYY-MM-DD). Strongly "
                "recommended for a first validation run against a "
                "production lake - omitting it replays every date on disk "
                "for the given symbol/channel."
            ),
        ),
    ] = None,
    report_path: Annotated[
        Path | None, typer.Option(help="Optional atomic JSON report output path.")
    ] = None,
) -> None:
    events = iter_raw_events(
        data_dir,
        exchange="bybit",
        market_type="linear",
        symbol=symbol,
        utc_date=utc_date,
        verify=True,
    )
    report = replay_bybit_stream(events).to_dict()
    output = json.dumps(report, sort_keys=True, indent=2) + "\n"
    if report_path is None:
        typer.echo(output, nl=False)
        return
    _atomic_write(report_path, output)
    typer.echo(f"Verified {report['raw_event_count']} raw events; report: {report_path}")


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
