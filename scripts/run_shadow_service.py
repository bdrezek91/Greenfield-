"""Entrypoint for the SHADOW service process (Cycle 2). Runs
src.execution.shadow_service.run_shadow_service under real SIGTERM/SIGINT
handling and exits with its returned exit code - see that module's
docstring for the exit code meanings (0 clean, 2 preflight failed, 3 fatal
event-loop error, 4 startup state reconciliation failed).

No execution adapter path exists in this process; it can never submit a
real order. Deliberately not started by a default `docker compose up` -
see the shadow-service entry in docker-compose.yml (profiles: ["shadow"]).

Usage:
    python scripts/run_shadow_service.py \
        --session-id shadow-20260823 \
        --dataset-fingerprint <sha256> \
        --config-fingerprint <sha256>
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import typer

from src.execution.shadow_runtime import ShadowSessionContext
from src.execution.shadow_service import run_shadow_service

app = typer.Typer(add_completion=False)


@app.command()
def main(
    session_id: str = typer.Option(..., help="Stable identifier for this SHADOW session."),
    dataset_fingerprint: str = typer.Option(..., help="SHA-256 (or similar) of the input dataset."),
    config_fingerprint: str = typer.Option(..., help="SHA-256 (or similar) of the active config."),
    code_commit: str = typer.Option(
        None, help="Defaults to $GREENFIELD_DEPLOY_COMMIT."
    ),
    data_dir: str = typer.Option(None, help="Defaults to $DATA_DIR or ./data"),
) -> None:
    resolved_code_commit = code_commit or os.environ.get("GREENFIELD_DEPLOY_COMMIT", "")
    resolved_data_dir = Path(data_dir or os.environ.get("DATA_DIR", "./data"))

    context = ShadowSessionContext(
        session_id=session_id,
        dataset_fingerprint=dataset_fingerprint,
        code_commit=resolved_code_commit,
        config_fingerprint=config_fingerprint,
    )
    shadow_dir = resolved_data_dir / "shadow" / session_id
    exit_code = run_shadow_service(
        context=context,
        env=os.environ,
        queue_db_path=shadow_dir / "queue.sqlite3",
        work_store_dir=shadow_dir / "work",
        risk_state_path=shadow_dir / "risk-state.json",
        audit_journal_path=shadow_dir / "audit.jsonl",
        health_path=resolved_data_dir / "health" / f"shadow-service-{session_id}.json",
    )
    sys.exit(exit_code)


if __name__ == "__main__":
    app()
