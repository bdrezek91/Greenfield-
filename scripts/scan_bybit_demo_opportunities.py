"""One public-data opportunity scan; never submits an order."""

from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path
from typing import Annotated

import typer

from src.engines.contracts import NumericRange
from src.execution.bybit_demo_opportunity_feed import PybitBybitOpportunityFeed
from src.execution.demo_opportunity_scanner import (
    DemoOpportunityScanner,
    PromotedEdgeProfile,
)
from src.execution.hybrid_bybit_opportunity_feed import HybridBybitOpportunityFeed

app = typer.Typer(add_completion=False)


@app.command()
def scan(
    symbols: str = typer.Option(
        "BTCUSDT,ETHUSDT,SOLUSDT", help="Comma-separated Bybit linear symbols."
    ),
    data_dir: Annotated[
        Path | None,
        typer.Option(
            help="Require verified local 5m history and at least three Bronze trade dates."
        ),
    ] = None,
) -> None:
    """Print an auditable LONG/SHORT/WAIT scan for each requested symbol."""
    requested = tuple(item.strip().upper() for item in symbols.split(",") if item.strip())
    if not requested or len(set(requested)) != len(requested):
        raise typer.BadParameter("symbols must be a non-empty unique list")
    edge = PromotedEdgeProfile(
        candidate_id="directional-public-confluence-v1",
        promotion_state="RESEARCH_CANDIDATE",
        expected_gross_value_bps=NumericRange(0.0, 0.0, 0.0),
        expected_cost_bps=NumericRange(2.0, 4.0, 8.0),
        capacity_notional=100.0,
    )
    public_feed = PybitBybitOpportunityFeed()
    hybrid_feed = (
        HybridBybitOpportunityFeed(data_dir=data_dir, public_feed=public_feed)
        if data_dir is not None
        else None
    )
    scanner = DemoOpportunityScanner()
    output = []
    for symbol in requested:
        snapshot = (
            hybrid_feed.fetch(symbol=symbol)
            if hybrid_feed is not None
            else public_feed.fetch(symbol=symbol)
        )
        result = scanner.scan(snapshot, edge=edge)
        output.append(
            {
                "data_source": "historical-plus-bronze-plus-live" if hybrid_feed else "live",
                "symbol": symbol,
                "candidate_id": result.candidate_id,
                "promotion_state": edge.promotion_state,
                "action": result.decision.action.value,
                "reason_codes": list(result.decision.reason_codes),
                "momentum_veto": result.momentum_veto.value,
                "evidence": [
                    {
                        **asdict(item),
                        "family": item.family.value,
                        "max_source_timestamp_utc": item.max_source_timestamp_utc.isoformat(),
                    }
                    for item in result.evidence
                ],
            }
        )
    typer.echo(json.dumps(output, indent=2, sort_keys=True))


if __name__ == "__main__":
    app()
