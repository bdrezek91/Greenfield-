"""Container healthcheck for a raw market collector (Bybit, OKX, ...).

Resolves the health file from EXCHANGE/MARKET_TYPE/COLLECTOR_ID env vars
(defaulting to "bybit"/"linear"/"all" - the original, still-correct
behavior for the active Bybit soak, which sets none of these explicitly)
so the same script/image serves every exchange's collector without
changing what the Bybit collector's healthcheck resolves to.
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Annotated

import typer

from src.data.collector_health import evaluate_health

app = typer.Typer(add_completion=False)


@app.command()
def check(
    health_path: Annotated[
        Path | None, typer.Option(help="Collector health JSON path.")
    ] = None,
    max_age_secs: Annotated[
        float, typer.Option(help="Maximum heartbeat age.")
    ] = 30.0,
) -> None:
    collector_id = os.environ.get("COLLECTOR_ID", "all")
    exchange = os.environ.get("EXCHANGE", "bybit")
    market_type = os.environ.get("MARKET_TYPE", "linear")
    path = health_path or Path(os.environ.get("DATA_DIR", "./data")) / "health" / (
        f"{exchange}-{market_type}-{collector_id}.json"
    )
    try:
        snapshot = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        typer.echo(f"unhealthy: cannot read {path}: {exc}", err=True)
        raise typer.Exit(code=1) from exc
    errors = evaluate_health(
        snapshot, now_ns=time.time_ns(), max_heartbeat_age_secs=max_age_secs
    )
    if errors:
        typer.echo("unhealthy: " + "; ".join(errors), err=True)
        raise typer.Exit(code=1)
    typer.echo("healthy")


if __name__ == "__main__":
    app()
