"""Read-only, sanitized Bybit Demo account balance."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Annotated

import typer

from src.execution.bybit_demo_gateway import PybitBybitDemoGateway
from src.execution.demo_operator import load_demo_environment, require_demo_paper_environment

app = typer.Typer(add_completion=False)


@app.command()
def balance(
    env_file: Annotated[
        Path,
        typer.Option(help="Gitignored Bybit Demo environment file."),
    ] = Path("bybit-demo.env"),
) -> None:
    try:
        env = load_demo_environment(env_file)
        require_demo_paper_environment(env, order_submission=False)
        value = PybitBybitDemoGateway.from_env(env).account_balance()
    except (RuntimeError, ValueError) as exc:
        typer.echo(f"BYBIT DEMO BALANCE FAILED: {exc}", err=True)
        raise typer.Exit(code=2) from exc
    typer.echo(
        json.dumps(
            {
                "total_equity_usd": str(value.total_equity_usd),
                "total_wallet_balance_usd": str(value.total_wallet_balance_usd),
                "total_available_balance_usd": str(value.total_available_balance_usd),
            },
            indent=2,
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    app()
