"""Continuous experimental ATAS/MC scalper, hard-pinned to Bybit Demo."""

from __future__ import annotations

import json
import signal
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated

import typer

from src.engines.contracts import NumericRange, SetupAction
from src.execution.bybit_demo_gateway import PybitBybitDemoGateway, PybitPublicLinearMarketData
from src.execution.demo_autonomous_state import AutonomousDemoStateStore
from src.execution.demo_operator import load_demo_environment
from src.execution.demo_opportunity_scanner import DemoOpportunityScanner, PromotedEdgeProfile
from src.execution.demo_scalp_executor import DemoScalpExecutor
from src.execution.hybrid_bybit_opportunity_feed import HybridBybitOpportunityFeed
from src.execution.paper_reconciliation import PaperOrderStore

app = typer.Typer(add_completion=False)
_stop = False


def _request_stop(_signum: int, _frame: object) -> None:
    global _stop
    _stop = True


@app.command()
def run(
    env_file: Annotated[Path, typer.Option()] = Path("bybit-demo.env"),
    data_dir: Annotated[Path, typer.Option()] = Path("data"),
    state_dir: Annotated[Path, typer.Option()] = Path("data/state/demo-scalp"),
    poll_seconds: Annotated[int, typer.Option(min=10)] = 30,
) -> None:
    env = load_demo_environment(env_file)
    gateway = PybitBybitDemoGateway.from_env(env)
    public_market = PybitPublicLinearMarketData()
    executor = DemoScalpExecutor(
        gateway=gateway,
        public_market=public_market,
        orders=PaperOrderStore(state_dir / "orders.sqlite3"),
        state=AutonomousDemoStateStore(state_dir / "lifecycle.sqlite3"),
    )
    feed = HybridBybitOpportunityFeed(data_dir=data_dir)
    scanner = DemoOpportunityScanner()
    edge = PromotedEdgeProfile(
        candidate_id="EXPERIMENTAL_DEMO_SCALP_ATAS_MC_V1",
        promotion_state="DEMO_EXPERIMENT_ONLY_NOT_PROMOTED",
        expected_gross_value_bps=NumericRange(0, 0, 0),
        expected_cost_bps=NumericRange(0, 0, 0),
        capacity_notional=0,
    )
    signal.signal(signal.SIGTERM, _request_stop)
    signal.signal(signal.SIGINT, _request_stop)
    state_dir.mkdir(parents=True, exist_ok=True)
    while not _stop:
        now = datetime.now(UTC)
        active = executor.state.active_trade()
        symbol = active.symbol if active is not None else "BTCUSDT"
        action = SetupAction.WAIT
        observation_id = f"{symbol}:{now.isoformat(timespec='seconds')}"
        if active is None:
            scan = scanner.scan(feed.fetch(symbol=symbol), edge=edge)
            action = scan.experimental_demo_action()
        result = executor.advance(
            env=env,
            symbol=symbol,
            action=action,
            observation_id=observation_id,
            candidate_id=edge.candidate_id,
            now_utc=now,
        )
        payload = {
            "timestamp_utc": now.isoformat(),
            "status": result.status,
            "detail": result.detail,
            "symbol": result.trade.symbol if result.trade else symbol,
            "trade_id": result.trade.trade_id if result.trade else None,
            "experimental_not_promoted": True,
        }
        (state_dir / "health.json").write_text(
            json.dumps(payload, sort_keys=True) + "\n", encoding="utf-8"
        )
        typer.echo(json.dumps(payload, sort_keys=True), err=True)
        if not _stop:
            time.sleep(poll_seconds)


if __name__ == "__main__":
    app()
