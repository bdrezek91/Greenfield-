"""Audit realized maker/taker fee rates from bounded Bybit Demo probes."""

from __future__ import annotations

import json
import sqlite3
from collections import defaultdict
from decimal import Decimal
from pathlib import Path
from typing import Annotated, Any

import typer

app = typer.Typer(add_completion=False)


def audit_observed_fee_rates(journal_path: Path) -> dict[str, Any]:
    journal = Path(journal_path).resolve(strict=True)
    grouped: dict[tuple[str, str], list[Decimal]] = defaultdict(list)
    with sqlite3.connect(journal) as connection:
        rows = connection.execute(
            """
            SELECT symbol, probe_mode, filled_price, filled_quantity, fee_cost_quote
            FROM execution_probe_orders
            WHERE rejected = 0 AND filled_quantity > 0
            ORDER BY recorded_at_utc, order_id
            """
        ).fetchall()
    for symbol, mode, price, quantity, fee in rows:
        notional = Decimal(str(price)) * Decimal(str(quantity))
        fee_quote = Decimal(str(fee))
        if notional <= 0 or fee_quote < 0 or mode not in {"MAKER", "TAKER"}:
            raise ValueError("execution probe journal contains an invalid fee observation")
        grouped[(str(symbol), str(mode))].append(fee_quote / notional * Decimal(10_000))
    if not grouped:
        raise ValueError("execution probe journal contains no filled fee observations")
    buckets = []
    for (symbol, mode), values in sorted(grouped.items()):
        buckets.append(
            {
                "symbol": symbol,
                "mode": mode,
                "observation_count": len(values),
                "mean_fee_bps": str(sum(values, Decimal(0)) / len(values)),
                "minimum_fee_bps": str(min(values)),
                "maximum_fee_bps": str(max(values)),
            }
        )
    return {
        "schema_version": 1,
        "source": "OBSERVED_BYBIT_DEMO_EXECUTIONS",
        "buckets": buckets,
        "promotion_allowed": False,
    }


@app.command()
def rates(
    journal_path: Annotated[
        Path,
        typer.Option(help="Execution-probe SQLite journal."),
    ] = Path("data/state/paper-execution-probe/journal.sqlite3"),
) -> None:
    try:
        report = audit_observed_fee_rates(journal_path)
    except (OSError, sqlite3.Error, ValueError) as exc:
        typer.echo(f"BYBIT DEMO FEE-RATE AUDIT FAILED: {exc}", err=True)
        raise typer.Exit(code=2) from exc
    typer.echo(json.dumps(report, indent=2, sort_keys=True))


if __name__ == "__main__":
    app()
