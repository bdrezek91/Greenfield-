"""CLI: run the Phase 15 LIVE readiness gate and print a pass/fail report.

This does NOT start live trading - src/execution/kraken_adapter.py can
technically accept TradingMode.LIVE, but no script in this repository ever
constructs it that way (scripts/paper_trade.py and
scripts/run_paper_session.py both hard-require TRADING_MODE=PAPER; there
is deliberately no scripts/live_trade.py). This script exists so the
automated half of "is it safe to go live" - as distinct from the
operational/manual half, see docs/LIVE_READINESS_CHECKLIST.md - can be
checked and recorded before that live entry point is ever built or used.

Exits non-zero if any check fails.

Usage:
    export TRADING_MODE=LIVE
    export CONFIRM_LIVE_TRADING=I_UNDERSTAND_THE_RISK
    export KRAKEN_API_KEY=... KRAKEN_API_SECRET=...
    python scripts/live_preflight_check.py \
        --risk-per-trade 0.01 --max-portfolio-risk 0.05 \
        --max-daily-loss 0.03 --max-drawdown 0.2 --max-leverage 3.0
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import structlog
import typer

from src.execution.live_preflight import LiveRiskBounds, run_preflight
from src.risk.engine import RiskConfig

log = structlog.get_logger()
app = typer.Typer(add_completion=False)


@app.command()
def check(
    risk_per_trade: float = typer.Option(..., help="Intended risk_per_trade for live."),
    max_portfolio_risk: float = typer.Option(..., help="Intended max_portfolio_risk for live."),
    max_daily_loss: float = typer.Option(..., help="Intended max_daily_loss for live."),
    max_drawdown: float = typer.Option(..., help="Intended max_drawdown for live."),
    max_leverage: float = typer.Option(..., help="Intended max_leverage for live."),
    experiments_path: str = typer.Option(
        "reports/experiments/experiments.jsonl", help="Recorded experiment log to check."
    ),
    min_experiments: int = typer.Option(1, help="Minimum recorded experiments required."),
) -> None:
    risk_config = RiskConfig(
        risk_per_trade=risk_per_trade,
        max_portfolio_risk=max_portfolio_risk,
        max_daily_loss=max_daily_loss,
        max_drawdown=max_drawdown,
        max_leverage=max_leverage,
    )
    report = run_preflight(
        env=os.environ,
        risk_config=risk_config,
        experiments_path=Path(experiments_path),
        bounds=LiveRiskBounds(),
        min_experiments=min_experiments,
    )

    for c in report.checks:
        (log.info if c.passed else log.error)(c.name, passed=c.passed, detail=c.detail)

    if not report.all_passed:
        log.error(
            "LIVE preflight FAILED",
            n_failed=len(report.failures()),
            note="see docs/LIVE_READINESS_CHECKLIST.md for the manual checklist too",
        )
        sys.exit(1)

    log.info(
        "LIVE preflight PASSED (automated checks only)",
        note="docs/LIVE_READINESS_CHECKLIST.md's manual items must ALSO be "
        "signed off - and no live execution path exists in this repository yet regardless",
    )


if __name__ == "__main__":
    app()
