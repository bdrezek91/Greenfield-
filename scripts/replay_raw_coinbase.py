"""Verify manifests and deterministically replay captured Coinbase raw data.

Mirrors scripts/replay_raw_bybit.py / replay_raw_binance.py /
replay_raw_okx.py, but deliberately has NO `--symbol` filter: Coinbase's
`sequence_num` is connection-global (see
src/data/coinbase_replay.py's module docstring), so silently dropping one
product's raw events before replay would make the connection-wide gate
see gaps that were actually just filtered-out messages, not real ones -
false positives, not a safety improvement. Always replays every product
captured on the connection together.
"""

from __future__ import annotations

import json
import os
import uuid
from pathlib import Path
from typing import Annotated

import typer

from src.data.coinbase_replay import replay_coinbase_stream
from src.data.raw_store import iter_raw_events

app = typer.Typer(add_completion=False)


@app.command()
def replay(
    data_dir: Annotated[Path, typer.Option(help="Greenfield data root.")] = Path("data"),
    report_path: Annotated[
        Path | None, typer.Option(help="Optional atomic JSON report output path.")
    ] = None,
) -> None:
    events = iter_raw_events(
        data_dir,
        exchange="coinbase",
        market_type="spot",
        verify=True,
    )
    report = replay_coinbase_stream(events).to_dict()
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
