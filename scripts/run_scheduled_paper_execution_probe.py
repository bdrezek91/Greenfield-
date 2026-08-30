"""Run one idempotent, bounded Bybit Demo execution probe per two-hour slot."""

from __future__ import annotations

import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated

import typer

SYMBOLS = ("BTCUSDT", "ETHUSDT", "SOLUSDT")

app = typer.Typer(add_completion=False)


def scheduled_identity(now_utc: datetime) -> tuple[str, str]:
    if now_utc.tzinfo is None:
        raise ValueError("scheduled probe timestamp must be timezone-aware")
    now = now_utc.astimezone(UTC)
    slot = now.hour // 2
    absolute_slot = now.date().toordinal() * 12 + slot
    symbol = SYMBOLS[absolute_slot % len(SYMBOLS)]
    request_id = f"probe-scheduled-{now:%Y%m%d}t{slot * 2:02d}00z"
    return symbol, request_id


@app.command()
def run(
    env_file: Annotated[Path, typer.Option(help="Gitignored Bybit Demo environment file.")],
    state_dir: Annotated[Path, typer.Option(help="Durable execution-probe state directory.")],
) -> None:
    symbol, request_id = scheduled_identity(datetime.now(UTC))
    probe = Path(__file__).resolve().with_name("run_paper_execution_probe.py")
    completed = subprocess.run(
        [
            sys.executable,
            str(probe),
            "--request-id",
            request_id,
            "--symbol",
            symbol,
            "--target-notional-quote",
            "30",
            "--maximum-notional-quote",
            "60",
            "--maker-fill-timeout-seconds",
            "20",
            "--maximum-orders-per-utc-day",
            "12",
            "--cooldown-seconds",
            "30",
            "--maximum-daily-loss-usd",
            "10",
            "--env-file",
            str(env_file),
            "--state-dir",
            str(state_dir),
        ],
        check=False,
    )
    raise typer.Exit(code=completed.returncode)


if __name__ == "__main__":
    app()
