"""Read-only Bybit Demo account fee-rate audit for BTC, ETH and SOL."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Annotated

import typer

from src.execution.bybit_demo_gateway import PybitBybitDemoGateway
from src.execution.demo_operator import load_demo_environment, require_demo_paper_environment

app = typer.Typer(add_completion=False)
_SYMBOLS = ("BTCUSDT", "ETHUSDT", "SOLUSDT")


@app.command()
def rates(
    env_file: Annotated[
        Path,
        typer.Option(help="Gitignored Bybit Demo environment file."),
    ] = Path("bybit-demo.env"),
) -> None:
    try:
        env = load_demo_environment(env_file)
        require_demo_paper_environment(env, order_submission=False)
        gateway = PybitBybitDemoGateway.from_env(env)
        values = [gateway.fee_rate(symbol=symbol) for symbol in _SYMBOLS]
    except (RuntimeError, ValueError) as exc:
        typer.echo(f"BYBIT DEMO FEE-RATE AUDIT FAILED: {exc}", err=True)
        raise typer.Exit(code=2) from exc
    typer.echo(
        json.dumps(
            {
                value.symbol: {
                    "maker_fee_rate": str(value.maker_fee_rate),
                    "maker_fee_bps": str(value.maker_fee_rate * 10_000),
                    "taker_fee_rate": str(value.taker_fee_rate),
                    "taker_fee_bps": str(value.taker_fee_rate * 10_000),
                }
                for value in values
            },
            indent=2,
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    app()
