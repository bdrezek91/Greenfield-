"""Operator-only Bybit Demo execution-quality probe (virtual funds only).

Disabled by default: requires BOTH `GREENFIELD_DEMO_ORDER_CONFIRMATION=
BYBIT_DEMO_ONLY` and `GREENFIELD_DEMO_EXECUTION_PROBE_CONFIRMATION=
EXECUTION_EVIDENCE_ONLY` in the environment file before it will submit a
single order. See docs/BYBIT_DEMO_RUNBOOK.md.

This is a single bounded round trip, not a continuous service: one call
places (or resumes) exactly one forced, tagged `EXECUTION_PROBE` order,
waits for a terminal fill/reject/cancel, immediately reduce-only-flattens
any resulting exposure, then polls public quotes for post-fill markouts.
Run it again (a fresh process, cron, or the /loop skill) for the next probe;
there is no persistent daemon here.
"""

from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path
from typing import Annotated, Any

import typer

from src.data.bybit_ticker_client import BybitTickerClient
from src.execution.bybit_demo_gateway import PybitBybitDemoGateway, PybitPublicLinearMarketData
from src.execution.demo_autonomous_state import (
    AutonomousDemoEntryNotAuthorizedError,
    AutonomousDemoStateStore,
)
from src.execution.demo_operator import load_demo_environment
from src.execution.execution_probe_journal import ExecutionProbeJournal
from src.execution.intent import IntentSide
from src.execution.paper_execution_probe import (
    PaperExecutionProbeConfig,
    PaperExecutionProbeExecutor,
    ProbeCycleResult,
    ProbeOrderType,
)
from src.execution.paper_reconciliation import PaperOrderStore

app = typer.Typer(add_completion=False)


@app.command()
def probe(
    request_id: Annotated[
        str,
        typer.Option(help="Stable ID; reuse it after any PENDING_RECONCILIATION rerun."),
    ],
    symbol: Annotated[str, typer.Option(help="BTCUSDT, ETHUSDT, or SOLUSDT.")],
    mode: Annotated[
        str | None,
        typer.Option(help="Force MAKER or TAKER; omit to alternate deterministically."),
    ] = None,
    side: Annotated[
        str | None,
        typer.Option(help="Force BUY or SELL; omit to alternate deterministically."),
    ] = None,
    target_notional_quote: Annotated[
        Decimal, typer.Option(help="Target virtual-USDT notional per probe order.")
    ] = Decimal("30"),
    maximum_notional_quote: Annotated[
        Decimal,
        typer.Option(help="Hard per-order notional cap; bounded by the code-level ceiling."),
    ] = Decimal("60"),
    maker_fill_timeout_seconds: Annotated[
        int, typer.Option(help="Cancel an unfilled MAKER probe after this many seconds.")
    ] = 20,
    maximum_orders_per_utc_day: Annotated[
        int, typer.Option(help="Daily probe order count cap (separate from any strategy's).")
    ] = 12,
    cooldown_seconds: Annotated[
        int, typer.Option(help="Minimum gap between probe entries.")
    ] = 30,
    maximum_daily_loss_usd: Annotated[
        Decimal, typer.Option(help="Absolute Demo-USDT daily loss cap for probe activity only.")
    ] = Decimal("10"),
    env_file: Annotated[
        Path, typer.Option(help="Gitignored Bybit Demo environment file.")
    ] = Path("bybit-demo.env"),
    state_dir: Annotated[
        Path,
        typer.Option(help="Durable state directory, kept separate from any future strategy's."),
    ] = Path("data/state/paper-execution-probe"),
) -> None:
    try:
        env = load_demo_environment(env_file)
        gateway = PybitBybitDemoGateway.from_env(env)
        executor = PaperExecutionProbeExecutor(
            gateway=gateway,
            public_market=PybitPublicLinearMarketData(),
            ticker=BybitTickerClient(),
            orders=PaperOrderStore(state_dir / "orders.sqlite3"),
            state=AutonomousDemoStateStore(state_dir / "lifecycle.sqlite3"),
            journal=ExecutionProbeJournal(state_dir / "journal.sqlite3"),
            config=PaperExecutionProbeConfig(
                target_notional_quote_usd=target_notional_quote,
                maximum_notional_quote_usd=maximum_notional_quote,
                maker_fill_timeout_seconds=maker_fill_timeout_seconds,
                maximum_orders_per_utc_day=maximum_orders_per_utc_day,
                cooldown_seconds=cooldown_seconds,
                maximum_daily_loss_usd=maximum_daily_loss_usd,
            ),
        )
        result = executor.run(
            env=env,
            symbol=symbol.upper(),
            request_id=request_id,
            mode_override=ProbeOrderType(mode.upper()) if mode else None,
            side_override=IntentSide(side.upper()) if side else None,
        )
    except AutonomousDemoEntryNotAuthorizedError as exc:
        typer.echo(json.dumps({"status": "WAIT", "detail": str(exc)}, indent=2))
        raise typer.Exit(code=0) from None
    except (RuntimeError, ValueError) as exc:
        typer.echo(f"EXECUTION PROBE FAILED: {exc}", err=True)
        raise typer.Exit(code=2) from exc

    typer.echo(json.dumps(_sanitized(result), indent=2, sort_keys=True))
    if result.status == "PENDING_RECONCILIATION":
        typer.echo(
            "Outcome remains unresolved; rerun the exact command with the SAME --request-id.",
            err=True,
        )
        raise typer.Exit(code=3)
    if result.status == "SAFETY_HOLD":
        typer.echo(
            "Execution probe is in SAFETY_HOLD; stop and inspect manually before retrying.",
            err=True,
        )
        raise typer.Exit(code=2)


def _sanitized(result: ProbeCycleResult) -> dict[str, Any]:
    trade = result.trade
    return {
        "status": result.status,
        "detail": result.detail,
        "trade": None
        if trade is None
        else {
            "trade_id": trade.trade_id,
            "candidate_id": trade.candidate_id,
            "symbol": trade.symbol,
            "action": trade.action.value,
            "phase": trade.phase.value,
            "target_quantity": str(trade.target_quantity),
            "reference_price": str(trade.reference_price),
            "realized_pnl_usd": str(trade.realized_pnl_usd) if trade.realized_pnl_usd else None,
        },
    }


if __name__ == "__main__":
    app()
