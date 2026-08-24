"""Clear a Demo safety hold only when no order or exposure ever existed."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated

import typer

from src.execution.bybit_demo_gateway import PybitBybitDemoGateway
from src.execution.demo_autonomous_state import AutonomousDemoStateStore
from src.execution.demo_operator import load_demo_environment, require_demo_paper_environment

app = typer.Typer(add_completion=False)


@app.command()
def clear(
    env_file: Annotated[Path, typer.Option()] = Path("bybit-demo.env"),
    state_file: Annotated[Path, typer.Option()] = Path("data/state/demo-scalp/lifecycle.sqlite3"),
) -> None:
    env = load_demo_environment(env_file)
    require_demo_paper_environment(env, order_submission=False)
    gateway = PybitBybitDemoGateway.from_env(env)
    gateway.preflight()
    exposure = gateway.account_exposure()
    if exposure.positions or exposure.open_orders:
        raise typer.BadParameter("Demo account is not flat; refusing to clear safety hold")
    store = AutonomousDemoStateStore(state_file)
    trade = store.active_trade()
    if trade is None:
        typer.echo("No active Demo scalp trade; nothing to clear.")
        return
    closed = store.close_unsubmitted_safety_hold(trade.trade_id, closed_at_utc=datetime.now(UTC))
    typer.echo(
        json.dumps(
            {
                "trade_id": closed.trade_id,
                "phase": closed.phase.value,
                "exit_reason": closed.exit_reason,
            },
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    app()
