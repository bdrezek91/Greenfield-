"""Explicitly armed, bounded PostOnly place/cancel smoke test on Bybit Demo."""

from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path
from typing import Annotated

import typer

from src.execution.bybit_demo_gateway import PybitBybitDemoGateway
from src.execution.demo_operator import (
    DemoSmokeRequest,
    load_demo_environment,
    run_demo_smoke,
    sanitized_smoke,
)
from src.execution.paper_reconciliation import PaperOrderState, PaperOrderStore

app = typer.Typer(add_completion=False)


@app.command()
def smoke_order(
    request_id: Annotated[
        str,
        typer.Option(
            help="Stable operator ID; reuse it after interruption, never invent a retry ID."
        ),
    ],
    symbol: Annotated[str, typer.Option(help="BTCUSDT, ETHUSDT, or SOLUSDT.")],
    side: Annotated[str, typer.Option(help="BUY or SELL.")],
    notional_quote: Annotated[
        Decimal,
        typer.Option(help="Explicit virtual-USDT notional, maximum 250."),
    ],
    reference_price: Annotated[Decimal, typer.Option(help="Observed market reference price.")],
    limit_price: Annotated[
        Decimal,
        typer.Option(help="Passive PostOnly limit: below reference for BUY, above for SELL."),
    ],
    env_file: Annotated[
        Path,
        typer.Option(help="Gitignored Bybit Demo environment file."),
    ] = Path("bybit-demo.env"),
    state_path: Annotated[
        Path,
        typer.Option(help="Durable local PAPER reconciliation database."),
    ] = Path("data/state/bybit-demo-paper.sqlite3"),
) -> None:
    try:
        env = load_demo_environment(env_file)
        gateway = PybitBybitDemoGateway.from_env(env)
        request = DemoSmokeRequest(
            request_id=request_id,
            symbol=symbol.upper(),
            side=side.upper(),
            notional_quote=notional_quote,
            reference_price=reference_price,
            limit_price=limit_price,
        )
        result = run_demo_smoke(
            gateway,
            PaperOrderStore(state_path),
            request,
            env=env,
        )
    except (RuntimeError, ValueError) as exc:
        typer.echo(f"BYBIT DEMO SMOKE FAILED: {exc}", err=True)
        raise typer.Exit(code=2) from exc
    typer.echo(json.dumps(sanitized_smoke(result), indent=2, sort_keys=True))
    if result.reconciliation.paper_order.state not in {
        PaperOrderState.CANCELED,
        PaperOrderState.FILLED,
        PaperOrderState.REJECTED,
    }:
        typer.echo(
            "Order is not exchange-confirmed terminal; rerun with the SAME --request-id.",
            err=True,
        )
        raise typer.Exit(code=3)


if __name__ == "__main__":
    app()
