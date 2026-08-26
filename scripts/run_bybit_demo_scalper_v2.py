"""Continuous "druga proba scalpingu" liquidation-fade candidate, hard-pinned
to Bybit Demo. See docs/CLAUDE_CODE_CONTINUATION.md for the research
rationale and src/execution/demo_opportunity_scanner_v2.py for the decision
logic. Cannot safely run alongside scripts/run_bybit_demo_scalper.py (v1) on
the same Bybit Demo API key - both executors refuse to trade the instant
they see exchange exposure/orders they didn't themselves open, so stop v1
before starting this.
"""

from __future__ import annotations

import json
import signal
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated

import typer

from src.engines.contracts import SetupAction
from src.execution.bybit_demo_gateway import PybitBybitDemoGateway, PybitPublicLinearMarketData
from src.execution.bybit_demo_opportunity_feed import (
    BybitOpportunityFeedError,
    PybitBybitOpportunityFeed,
)
from src.execution.demo_autonomous_risk import AtrExitConfig, AutonomousDemoRiskConfig
from src.execution.demo_autonomous_state import (
    AutonomousDemoEntryNotAuthorizedError,
    AutonomousDemoStateStore,
)
from src.execution.demo_operator import load_demo_environment
from src.execution.demo_opportunity_scanner_v2 import (
    LIQUIDATION_FADE_CANDIDATE_ID,
    scan_liquidation_fade,
)
from src.execution.demo_scalp_executor import DemoScalpCycleResult, DemoScalpExecutor
from src.execution.demo_scalp_health import DemoScalpHealthPublisher
from src.execution.demo_scalp_liquidation_feed import (
    BronzeLiquidationFeedConfig,
    BronzeLiquidationFeedError,
    fetch_recent_liquidations,
)
from src.execution.demo_scalp_liquidation_signal import (
    FundingRegimeConfig,
    LiquidationCascadeConfig,
)
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
    state_dir: Annotated[Path, typer.Option()] = Path("data/state/demo-scalp-v2"),
    poll_seconds: Annotated[int, typer.Option(min=10)] = 30,
) -> None:
    env = load_demo_environment(env_file)
    gateway = PybitBybitDemoGateway.from_env(env)
    public_market = PybitPublicLinearMarketData()
    opportunity_feed = PybitBybitOpportunityFeed()
    executor = DemoScalpExecutor(
        gateway=gateway,
        public_market=public_market,
        orders=PaperOrderStore(state_dir / "orders.sqlite3"),
        state=AutonomousDemoStateStore(state_dir / "lifecycle.sqlite3"),
        config=AutonomousDemoRiskConfig(
            maximum_trades_per_utc_day=12,
            maximum_holding_seconds=600,
            cooldown_seconds=300,
        ),
        atr_exit_config=AtrExitConfig(),
        use_post_only_entry=True,
    )
    cascade_config = LiquidationCascadeConfig()
    funding_config = FundingRegimeConfig()
    liquidation_feed_config = BronzeLiquidationFeedConfig(
        fetch_window_seconds=cascade_config.reference_window_seconds
    )
    signal.signal(signal.SIGTERM, _request_stop)
    signal.signal(signal.SIGINT, _request_stop)
    state_dir.mkdir(parents=True, exist_ok=True)
    health = DemoScalpHealthPublisher(state_dir / "health.json")
    while not _stop:
        now = datetime.now(UTC)
        active = executor.state.active_trade()
        symbol = active.symbol if active is not None else "BTCUSDT"
        action = SetupAction.WAIT
        wait_detail: str | None = None
        candles = None
        observation_id = f"{symbol}:{now.isoformat(timespec='seconds')}"
        if active is None:
            try:
                snapshot = opportunity_feed.fetch(symbol=symbol, observed_at_utc=now)
                candles = snapshot.candles
                liquidations = fetch_recent_liquidations(
                    data_dir,
                    symbol=symbol,
                    observed_at_utc=now,
                    config=liquidation_feed_config,
                )
                funding = public_market.funding_snapshot(symbol=symbol)
                scan = scan_liquidation_fade(
                    symbol=symbol,
                    liquidations=liquidations,
                    funding_rate=funding.funding_rate,
                    observed_at_utc=now,
                    cascade_config=cascade_config,
                    funding_config=funding_config,
                )
                action = scan.action
                if action is SetupAction.WAIT:
                    wait_detail = scan.detail
            except (BybitOpportunityFeedError, BronzeLiquidationFeedError) as exc:
                wait_detail = f"INSUFFICIENT_DATA:{type(exc).__name__}:{exc}"
        try:
            result = executor.advance(
                env=env,
                symbol=symbol,
                action=action,
                observation_id=observation_id,
                candidate_id=LIQUIDATION_FADE_CANDIDATE_ID,
                now_utc=now,
                candles=candles,
            )
        except AutonomousDemoEntryNotAuthorizedError as exc:
            result = DemoScalpCycleResult(
                "WAIT", executor.state.active_trade(), f"RISK_GATE:{exc}"
            )
        if wait_detail is not None and result.status == "WAIT":
            result = DemoScalpCycleResult(result.status, result.trade, wait_detail)
        payload = {
            "timestamp_utc": now.isoformat(),
            "status": result.status,
            "detail": result.detail,
            "symbol": result.trade.symbol if result.trade else symbol,
            "trade_id": result.trade.trade_id if result.trade else None,
            "candidate_id": LIQUIDATION_FADE_CANDIDATE_ID,
            "experimental_not_promoted": True,
        }
        health.publish(payload)
        typer.echo(json.dumps(payload, sort_keys=True), err=True)
        if not _stop:
            time.sleep(poll_seconds)


if __name__ == "__main__":
    app()
