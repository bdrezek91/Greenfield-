"""CLI: run exactly one autonomous research cycle and exit with a status
that reflects the outcome - never ambiguous, never a silent pass.

Exit codes:
    0  cycle completed, status CANDIDATE (a new RESEARCH_CANDIDATE was
       registered - still requires a human to promote it to PAPER)
    0  cycle completed, status NO_CANDIDATE (a valid, expected outcome -
       see docs/RESEARCH_METHODOLOGY.md)
    1  cycle aborted/errored (lock held by another worker, disk space,
       an unhandled exception) - operator attention needed

Usage:
    python scripts/run_research_cycle.py --data-dir ./data
"""

from __future__ import annotations

import os
from decimal import Decimal
from pathlib import Path

import pandas as pd
import structlog
import typer

from src.research.config import DEFAULT_PROTOCOL_PATH, load_research_protocol
from src.research.orchestrator import CycleConfig, run_cycle

log = structlog.get_logger()
app = typer.Typer(add_completion=False)


@app.command()
def main(
    data_dir: str | None = typer.Option(None, help="Defaults to $DATA_DIR or ./data"),
    protocol_path: str | None = typer.Option(None, help=f"Defaults to {DEFAULT_PROTOCOL_PATH}"),
    as_of: str | None = typer.Option(
        None, help="ISO date to bound available data; defaults to now (UTC)."
    ),
    starting_balance: float = typer.Option(100_000.0),
) -> None:
    resolved_data_dir = Path(data_dir or os.environ.get("DATA_DIR", "./data"))
    protocol = load_research_protocol(
        Path(protocol_path) if protocol_path else DEFAULT_PROTOCOL_PATH
    )
    as_of_ts = pd.Timestamp(as_of, tz="UTC") if as_of else pd.Timestamp.now(tz="UTC")

    config = CycleConfig(
        data_dir=resolved_data_dir,
        protocol=protocol,
        as_of=as_of_ts,
        starting_balance=Decimal(str(starting_balance)),
    )
    result = run_cycle(config)

    log.info(
        "research cycle finished",
        cycle_id=result.cycle_id,
        status=result.status,
        candidate=result.selected_candidate_hypothesis_id,
        global_trial_count=result.global_trial_count,
        passed=len(result.passed_trials),
        rejected=len(result.rejected_trials),
    )

    if result.status == "ERROR":
        log.error("research cycle aborted", error=result.error)
        raise typer.Exit(code=1)
    raise typer.Exit(code=0)


if __name__ == "__main__":
    app()
