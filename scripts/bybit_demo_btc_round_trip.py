"""Operator-only, recovery-safe BTC round-trip on Bybit Demo virtual funds."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Annotated, Any

import typer

from src.execution.bybit_demo_gateway import (
    BYBIT_PUBLIC_REST_URL,
    PybitBybitDemoGateway,
    PybitPublicLinearMarketData,
)
from src.execution.demo_btc_round_trip import (
    DemoBtcRoundTripCoordinator,
    DemoBtcRoundTripPhase,
    DemoBtcRoundTripRequest,
    DemoBtcRoundTripResult,
)
from src.execution.demo_operator import load_demo_environment
from src.execution.paper_reconciliation import PaperOrderRecord, PaperOrderStore

app = typer.Typer(add_completion=False)


@app.command()
def round_trip(
    request_id: Annotated[
        str,
        typer.Option(help="Stable retry ID; reuse it after every unresolved outcome."),
    ],
    env_file: Annotated[
        Path,
        typer.Option(help="Gitignored Bybit Demo environment file."),
    ] = Path("bybit-demo.env"),
    state_file: Annotated[
        Path,
        typer.Option(help="Durable SQLite state used to prevent duplicate submissions."),
    ] = Path("data/state/bybit-demo-btc-round-trip.sqlite3"),
) -> None:
    try:
        env = load_demo_environment(env_file)
        coordinator = DemoBtcRoundTripCoordinator(
            gateway=PybitBybitDemoGateway.from_env(env),
            public_market=PybitPublicLinearMarketData(),
            store=PaperOrderStore(state_file),
        )
        result = coordinator.advance(DemoBtcRoundTripRequest(request_id), env=env)
    except (RuntimeError, ValueError) as exc:
        typer.echo(f"BYBIT DEMO BTC ROUND-TRIP FAILED: {exc}", err=True)
        raise typer.Exit(code=2) from exc
    typer.echo(json.dumps(_sanitized_result(result), indent=2, sort_keys=True))
    if result.phase in {
        DemoBtcRoundTripPhase.ENTRY_UNRESOLVED,
        DemoBtcRoundTripPhase.CLOSE_UNRESOLVED,
    }:
        typer.echo(
            "Outcome remains unresolved; rerun the exact command with the same request ID.",
            err=True,
        )
        raise typer.Exit(code=3)


def _order(record: PaperOrderRecord) -> dict[str, Any]:
    return {
        "client_order_id": record.client_order_id,
        "side": record.side.value,
        "quantity": record.quantity,
        "state": record.state.value,
        "filled_quantity": record.filled_quantity,
        "average_fill_price": record.average_fill_price,
        "fee_cost_quote": record.fee_cost_quote,
    }


def _sanitized_result(result: DemoBtcRoundTripResult) -> dict[str, Any]:
    return {
        "phase": result.phase.value,
        "execution_endpoint": result.preflight.endpoint,
        "public_market_endpoint": BYBIT_PUBLIC_REST_URL,
        "symbol": result.market.symbol,
        "leverage": result.leverage,
        "target_notional_quote": str(result.target_notional_quote),
        "estimated_entry_notional_quote": str(result.estimated_entry_notional_quote),
        "submitted_quantity": str(result.submitted_quantity),
        "entry_order": _order(result.entry_order),
        "close_orders": [_order(order) for order in result.close_orders],
        "exchange_position_size": str(result.exchange_position_size),
        "paper_position_size": (
            result.paper_position.net_quantity if result.paper_position else None
        ),
    }


if __name__ == "__main__":
    app()
