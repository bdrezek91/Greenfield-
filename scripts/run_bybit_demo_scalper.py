"""Continuous experimental ATAS/MC scalper, hard-pinned to Bybit Demo."""

from __future__ import annotations

import json
import signal
import time
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Annotated

import typer

from src.engines.contracts import NumericRange, SetupAction
from src.execution.bybit_demo_gateway import PybitBybitDemoGateway, PybitPublicLinearMarketData
from src.execution.demo_autonomous_risk import AutonomousDemoRiskConfig
from src.execution.demo_autonomous_state import AutonomousDemoStateStore
from src.execution.demo_operator import load_demo_environment
from src.execution.demo_opportunity_scanner import DemoOpportunityScanner, PromotedEdgeProfile
from src.execution.demo_scalp_executor import DemoScalpExecutor
from src.execution.demo_scalp_health import DemoScalpHealthPublisher
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
    force_once: Annotated[str, typer.Option()] = "",
    stop_loss_bps: Annotated[int | None, typer.Option(min=1, max=99)] = None,
) -> None:
    env = load_demo_environment(env_file)
    force = (force_once or env.get("DEMO_SCALP_FORCE_ONCE", "")).upper()
    if force not in {"", "LONG", "SHORT"}:
        raise typer.BadParameter("force-once must be LONG, SHORT, or empty")
    configured_stop = stop_loss_bps or int(env.get("DEMO_SCALP_STOP_LOSS_BPS", "20"))
    if not 1 <= configured_stop <= 99:
        raise typer.BadParameter("stop-loss-bps must be between 1 and 99")
    gateway = PybitBybitDemoGateway.from_env(env)
    public_market = PybitPublicLinearMarketData()
    executor = DemoScalpExecutor(
        gateway=gateway,
        public_market=public_market,
        orders=PaperOrderStore(state_dir / "orders.sqlite3"),
        state=AutonomousDemoStateStore(state_dir / "lifecycle.sqlite3"),
        config=AutonomousDemoRiskConfig(
            maximum_trades_per_utc_day=12,
            maximum_holding_seconds=600,
            cooldown_seconds=300,
            stop_loss_bps=Decimal(configured_stop),
        ),
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
    force_marker = state_dir / "operator-force-once-consumed"
    health = DemoScalpHealthPublisher(state_dir / "health.json")
    while not _stop:
        now = datetime.now(UTC)
        active = executor.state.active_trade()
        symbol = active.symbol if active is not None else "BTCUSDT"
        action = SetupAction.WAIT
        observation_id = f"{symbol}:{now.isoformat(timespec='seconds')}"
        if active is None:
            if force and not force_marker.exists():
                action = SetupAction(force)
                observation_id = f"OPERATOR_FORCED:{force}:{now.isoformat(timespec='seconds')}"
            else:
                scan = scanner.scan(feed.fetch(symbol=symbol), edge=edge)
                action = scan.experimental_demo_action()
        candidate_id = (
            "OPERATOR_FORCED_DEMO_TEST_NOT_SIGNAL"
            if observation_id.startswith("OPERATOR_FORCED:")
            else edge.candidate_id
        )
        result = executor.advance(
            env=env,
            symbol=symbol,
            action=action,
            observation_id=observation_id,
            candidate_id=candidate_id,
            now_utc=now,
        )
        if candidate_id == "OPERATOR_FORCED_DEMO_TEST_NOT_SIGNAL" and result.trade:
            force_marker.write_text(result.trade.trade_id + "\n", encoding="utf-8")
        payload = {
            "timestamp_utc": now.isoformat(),
            "status": result.status,
            "detail": result.detail,
            "symbol": result.trade.symbol if result.trade else symbol,
            "trade_id": result.trade.trade_id if result.trade else None,
            "experimental_not_promoted": True,
            "operator_forced": candidate_id == "OPERATOR_FORCED_DEMO_TEST_NOT_SIGNAL",
        }
        health.publish(payload)
        typer.echo(json.dumps(payload, sort_keys=True), err=True)
        if not _stop:
            time.sleep(poll_seconds)


if __name__ == "__main__":
    app()
