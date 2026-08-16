"""CLI: compact microstructure batch files once, or continuously (for
`docker compose up -d data-compactor`).

Uses src/data/microstructure_compactor.py's atomic merge-validate-swap-
then-delete sequence - never removes source files before the merged
replacement is confirmed valid and already in place.

Usage:
    python scripts/compact_microstructure.py --once
    python scripts/compact_microstructure.py --interval-hours 24
"""

from __future__ import annotations

import os
import time
from pathlib import Path

import structlog
import typer

from src.data.microstructure_compactor import compact_all
from src.research.locking import GracefulShutdown

log = structlog.get_logger()
app = typer.Typer(add_completion=False)


def _run_once(data_dir: Path) -> None:
    results = compact_all(data_dir)
    ok = [r for r in results if r.ok and r.merged_path is not None]
    failed = [r for r in results if not r.ok and r.source_files > 1]
    log.info(
        "microstructure compaction pass finished",
        directories_scanned=len(results),
        directories_compacted=len(ok),
        directories_failed_validation=len(failed),
        total_files_merged=sum(r.source_files for r in ok),
    )
    for r in failed:
        log.error(
            "compaction validation failed - sources left untouched",
            directory=str(r.directory),
            reason=r.skipped_reason,
        )


@app.command()
def main(
    data_dir: str | None = typer.Option(None, help="Defaults to $DATA_DIR or ./data"),
    once: bool = typer.Option(False, help="Run a single pass and exit (default: loop)."),
    interval_hours: float = typer.Option(24.0, help="Hours between passes when looping."),
    poll_seconds: int = typer.Option(30, help="How often to check for shutdown while sleeping."),
) -> None:
    resolved_data_dir = Path(data_dir or os.environ.get("DATA_DIR", "./data"))

    if once:
        _run_once(resolved_data_dir)
        return

    with GracefulShutdown() as shutdown:
        while not shutdown.requested:
            _run_once(resolved_data_dir)
            slept = 0.0
            interval_seconds = interval_hours * 3600
            while slept < interval_seconds and not shutdown.requested:
                time.sleep(min(poll_seconds, interval_seconds - slept))
                slept += poll_seconds
    log.info("data-compactor shutting down cleanly")


if __name__ == "__main__":
    app()
