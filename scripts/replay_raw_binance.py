"""Verify manifests and deterministically replay captured Binance raw data.

Mirrors scripts/replay_raw_bybit.py. Requires Bronze data collected after
Cycle 19 (which persists the REST depth snapshot needed to bootstrap
order-book reconstruction) - see src/data/binance_replay.py's module
docstring for what happens on older data (BinanceSnapshotRequired).
"""

from __future__ import annotations

import json
import os
import uuid
from pathlib import Path
from typing import Annotated

import typer

from src.data.binance_replay import replay_binance_stream
from src.data.raw_store import iter_raw_events

app = typer.Typer(add_completion=False)


@app.command()
def replay(
    data_dir: Annotated[Path, typer.Option(help="Greenfield data root.")] = Path("data"),
    symbol: Annotated[
        str | None, typer.Option(help="Optional single-symbol filter.")
    ] = None,
    report_path: Annotated[
        Path | None, typer.Option(help="Optional atomic JSON report output path.")
    ] = None,
) -> None:
    events = iter_raw_events(
        data_dir,
        exchange="binance",
        market_type="linear",
        symbol=symbol,
        verify=True,
    )
    report = replay_binance_stream(events).to_dict()
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
