"""Long-running loop around run_research_cycle's logic: run one cycle, sleep
until the next one is due, repeat - until SIGTERM/SIGINT.

Deliberately a plain loop with a signal handler, not a scheduler framework
(cron/systemd timer calling scripts/run_research_cycle.py once is an
equally valid, and often simpler, deployment - see docs/VPS_DEPLOYMENT.md).
This script exists for the docker-compose `research-worker` service, which
wants one long-lived process it can health-check and restart.

Usage:
    python scripts/run_research_daemon.py --data-dir ./data --interval-hours 24
"""

from __future__ import annotations

import os
import time
from decimal import Decimal
from pathlib import Path

import pandas as pd
import structlog
import typer

from src.research.config import DEFAULT_PROTOCOL_PATH, load_research_protocol
from src.research.locking import GracefulShutdown
from src.research.orchestrator import CycleConfig, run_cycle

log = structlog.get_logger()
app = typer.Typer(add_completion=False)

DEFAULT_HEARTBEAT_PATH = Path("reports") / "research" / "worker_heartbeat"


def _touch_heartbeat(path: Path) -> None:
    """Written after every loop iteration (cycle attempt or sleep tick) so
    a Docker healthcheck can alert on "no heartbeat in N minutes" without
    needing to inspect cycle internals - see docker-compose.yml's
    research-worker healthcheck.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(pd.Timestamp.now(tz="UTC").isoformat())


@app.command()
def main(
    data_dir: str | None = typer.Option(None, help="Defaults to $DATA_DIR or ./data"),
    protocol_path: str | None = typer.Option(None),
    interval_hours: float = typer.Option(24.0, help="Hours between cycles."),
    starting_balance: float = typer.Option(100_000.0),
    poll_seconds: int = typer.Option(30, help="How often to check for shutdown while sleeping."),
    heartbeat_path: str | None = typer.Option(None, help=f"Defaults to {DEFAULT_HEARTBEAT_PATH}"),
) -> None:
    resolved_data_dir = Path(data_dir or os.environ.get("DATA_DIR", "./data"))
    resolved_heartbeat_path = Path(heartbeat_path) if heartbeat_path else DEFAULT_HEARTBEAT_PATH
    protocol = load_research_protocol(
        Path(protocol_path) if protocol_path else DEFAULT_PROTOCOL_PATH
    )

    with GracefulShutdown() as shutdown:
        while not shutdown.requested:
            config = CycleConfig(
                data_dir=resolved_data_dir,
                protocol=protocol,
                as_of=pd.Timestamp.now(tz="UTC"),
                starting_balance=Decimal(str(starting_balance)),
            )
            try:
                result = run_cycle(config)
                log.info(
                    "research cycle finished",
                    cycle_id=result.cycle_id,
                    status=result.status,
                    candidate=result.selected_candidate_hypothesis_id,
                )
            except Exception:  # noqa: BLE001 - the daemon must survive one bad cycle
                log.exception("research cycle raised - will retry next interval")
            _touch_heartbeat(resolved_heartbeat_path)

            slept = 0.0
            interval_seconds = interval_hours * 3600
            while slept < interval_seconds and not shutdown.requested:
                time.sleep(min(poll_seconds, interval_seconds - slept))
                slept += poll_seconds
                _touch_heartbeat(resolved_heartbeat_path)

    log.info("research daemon shutting down cleanly")


if __name__ == "__main__":
    app()
