"""Read-only, sanitized Bybit Demo credential and account preflight."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Annotated

import typer

from src.execution.bybit_demo_gateway import PybitBybitDemoGateway
from src.execution.demo_operator import (
    load_demo_environment,
    run_demo_preflight,
    sanitized_preflight,
)

app = typer.Typer(add_completion=False)


@app.command()
def preflight(
    env_file: Annotated[
        Path,
        typer.Option(help="Gitignored Bybit Demo environment file."),
    ] = Path("bybit-demo.env"),
) -> None:
    try:
        env = load_demo_environment(env_file)
        gateway = PybitBybitDemoGateway.from_env(env)
        report = run_demo_preflight(gateway, env=env)
    except (RuntimeError, ValueError) as exc:
        typer.echo(f"BYBIT DEMO PREFLIGHT FAILED: {exc}", err=True)
        raise typer.Exit(code=2) from exc
    typer.echo(json.dumps(sanitized_preflight(report), indent=2, sort_keys=True))


if __name__ == "__main__":
    app()
