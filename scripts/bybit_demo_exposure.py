"""Read-only, sanitized Bybit Demo positions and open orders."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Annotated

import typer

from src.execution.bybit_demo_gateway import PybitBybitDemoGateway
from src.execution.demo_operator import load_demo_environment, require_demo_paper_environment

app = typer.Typer(add_completion=False)


@app.command()
def exposure(
    env_file: Annotated[
        Path,
        typer.Option(help="Gitignored Bybit Demo environment file."),
    ] = Path("bybit-demo.env"),
) -> None:
    try:
        env = load_demo_environment(env_file)
        require_demo_paper_environment(env, order_submission=False)
        value = PybitBybitDemoGateway.from_env(env).account_exposure()
    except (RuntimeError, ValueError) as exc:
        typer.echo(f"BYBIT DEMO EXPOSURE FAILED: {exc}", err=True)
        raise typer.Exit(code=2) from exc
    typer.echo(
        json.dumps(
            {
                "nonzero_positions": [
                    {
                        "symbol": item.symbol,
                        "side": item.side,
                        "size": str(item.size),
                        "leverage": str(item.leverage),
                        "position_index": item.position_index,
                    }
                    for item in value.positions
                ],
                "open_orders": [
                    {
                        "order_id": item.order_id,
                        "order_link_id": item.order_link_id,
                        "symbol": item.symbol,
                        "side": item.side,
                        "order_type": item.order_type,
                        "quantity": str(item.quantity),
                        "leaves_quantity": str(item.leaves_quantity),
                        "reduce_only": item.reduce_only,
                    }
                    for item in value.open_orders
                ],
            },
            indent=2,
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    app()
