"""Capture controlled lag/partial-exit recovery evidence without placing an order."""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated

import typer

from src.execution.bybit_demo_gateway import PybitBybitDemoGateway
from src.execution.demo_fault_drill import (
    evaluate_demo_fault_drill,
    write_demo_fault_drill_report,
)
from src.execution.demo_operator import load_demo_environment, require_demo_paper_environment

app = typer.Typer(add_completion=False)

FAULT_TARGETS = (
    "tests/unit/test_demo_scalp_executor.py::test_execution_feed_lag_is_retried_without_crashing",
    "tests/unit/test_demo_scalp_executor.py::test_partial_canceled_exit_submits_residual_after_restart",
    "tests/unit/test_demo_btc_round_trip.py::test_order_history_ahead_of_executions_is_unresolved_then_recovers",
)


@app.command()
def capture(
    env_file: Annotated[Path, typer.Option(help="Gitignored Bybit Demo environment file.")] = Path(
        "bybit-demo.env"
    ),
    repository_root: Annotated[Path, typer.Option()] = Path("."),
    report_path: Annotated[Path, typer.Option()] = Path(
        "reports/demo-fault-drills/latest.json"
    ),
) -> None:
    root = repository_root.resolve()
    started = datetime.now(UTC)
    try:
        source_commit = _git(root, "rev-parse", "HEAD").strip()
        if _git(root, "status", "--porcelain").strip():
            raise RuntimeError("repository is dirty; refusing immutable drill evidence")
        env = load_demo_environment(env_file.resolve())
        require_demo_paper_environment(env, order_submission=False)
        gateway = PybitBybitDemoGateway.from_env(env)
        flat_before = _flat(gateway)
        if not flat_before:
            raise RuntimeError("Bybit Demo account is not flat before the drill")
        completed_tests = subprocess.run(
            [sys.executable, "-m", "pytest", "-q", *FAULT_TARGETS],
            cwd=root,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            check=False,
        )
        flat_after = _flat(gateway)
        output = completed_tests.stdout or ""
        report = evaluate_demo_fault_drill(
            source_commit=source_commit,
            started_at_utc=started.isoformat(),
            completed_at_utc=datetime.now(UTC).isoformat(),
            flat_before=flat_before,
            flat_after=flat_after,
            test_exit_code=completed_tests.returncode,
            test_output_sha256=hashlib.sha256(output.encode("utf-8")).hexdigest(),
            test_targets=FAULT_TARGETS,
        )
        write_demo_fault_drill_report(report_path.resolve(), report)
    except (OSError, RuntimeError, ValueError, subprocess.SubprocessError) as exc:
        typer.echo(f"BYBIT DEMO FAULT DRILL FAILED: {exc}", err=True)
        raise typer.Exit(code=2) from exc
    typer.echo(output.rstrip())
    typer.echo(json.dumps(report.to_dict(), indent=2, sort_keys=True))
    if not report.qualified:
        raise typer.Exit(code=2)


def _git(root: Path, *args: str) -> str:
    completed = subprocess.run(
        ["git", *args], cwd=root, text=True, capture_output=True, check=False
    )
    if completed.returncode != 0:
        raise RuntimeError(completed.stderr.strip() or "Git command failed")
    return completed.stdout


def _flat(gateway: PybitBybitDemoGateway) -> bool:
    exposure = gateway.account_exposure()
    return not exposure.positions and not exposure.open_orders


if __name__ == "__main__":
    app()
