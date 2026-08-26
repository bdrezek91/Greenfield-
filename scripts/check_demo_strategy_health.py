"""Fail-closed health check reusable by a future Bybit Demo strategy."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated

import typer

app = typer.Typer(add_completion=False)


@app.command()
def check(
    path: Annotated[Path, typer.Option()] = Path("data/state/demo-strategy/health.json"),
    maximum_age_seconds: Annotated[int, typer.Option(min=1)] = 120,
) -> None:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        timestamp = datetime.fromisoformat(str(payload["timestamp_utc"]))
        if timestamp.tzinfo is None:
            raise ValueError("timestamp is naive")
        age = (datetime.now(UTC) - timestamp.astimezone(UTC)).total_seconds()
        if age < 0 or age > maximum_age_seconds:
            raise ValueError(f"heartbeat age is {age:.1f}s")
        status = str(payload["status"])
        if status in {"ERROR", "SAFETY_HOLD"}:
            raise ValueError(f"unsafe status {status}")
    except (OSError, KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
        typer.echo(f"BYBIT DEMO STRATEGY UNHEALTHY: {exc}", err=True)
        raise typer.Exit(code=1) from exc
    typer.echo(f"BYBIT DEMO STRATEGY HEALTHY: {status}")


if __name__ == "__main__":
    app()
