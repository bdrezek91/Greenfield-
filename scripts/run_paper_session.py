"""CLI: run one strategy live against a Bybit simulation backend
("testnet" or "demo", see src/execution/paper_node.py) as a long-running,
supervised paper-trading session (Phase 14) - the durable counterpart to
scripts/paper_trade.py's single blocking `node.run()` call.

Adds, on top of scripts/paper_trade.py:
  - src/execution/session_recorder.py attached to the strategy, so real
    OrderFilled/OrderRejected events are scored against the intents that
    produced them (the section-32 comparison, now fed by a live run
    instead of only replayed backtest trades).
  - src/execution/supervisor.py: `node.run()` is retried with exponential
    backoff on failure (e.g. a testnet disconnect), instead of the whole
    process dying on the first one.
  - src/execution/session_state.py: session metadata (restart count, last
    error, latest fill summary) is checkpointed to `--checkpoint-path` so
    the session's operational history survives a full process restart,
    not just an in-process retry.

NOT VERIFIED IN THIS SESSION - same network egress restriction to
api.bybit.com documented in src/execution/paper_node.py's module
docstring. Validate on a machine with unrestricted network access before
relying on this for a real long-running session.

Usage:
    export TRADING_MODE=PAPER
    export BYBIT_API_KEY=...      # testnet key, see .env.example
    export BYBIT_API_SECRET=...
    python scripts/run_paper_session.py --symbol BTCUSDT --timeframe 1h \
        --strategy trend_following --checkpoint-path reports/paper_session.json
"""

from __future__ import annotations

import os
from pathlib import Path

import structlog
import typer
from nautilus_trader.model.data import BarSpecification, BarType
from nautilus_trader.model.enums import AggregationSource, BarAggregation, PriceType

from src.data.config import load_symbol_universe
from src.execution.mode import LiveTradingBlockedError, TradingMode, resolve_trading_mode
from src.execution.paper_node import (
    VALID_PAPER_BACKENDS,
    build_paper_trading_node,
    live_instrument_id_for,
)
from src.execution.session_recorder import SessionRecorder
from src.execution.supervisor import PaperSessionSupervisor, SupervisorConfig
from src.strategies.registry import ALL_STRATEGIES

log = structlog.get_logger()
app = typer.Typer(add_completion=False)

_TIMEFRAME_TO_BAR_AGGREGATION = {
    "1m": (1, BarAggregation.MINUTE),
    "5m": (5, BarAggregation.MINUTE),
    "15m": (15, BarAggregation.MINUTE),
    "1h": (1, BarAggregation.HOUR),
    "4h": (4, BarAggregation.HOUR),
    "1d": (1, BarAggregation.DAY),
}


@app.command()
def run(
    symbol: str = typer.Option(..., help="Single symbol, e.g. BTCUSDT."),
    timeframe: str = typer.Option("1h", help="Timeframe, e.g. 1h."),
    strategy: str = typer.Option(..., help=f"One of {list(ALL_STRATEGIES)}."),
    checkpoint_path: str = typer.Option(
        "reports/paper_session.json", help="Where to persist session state across restarts."
    ),
    max_restarts: int = typer.Option(5, help="Give up after this many consecutive failures."),
    backoff_seconds: float = typer.Option(30.0, help="Initial retry backoff."),
    backend: str = typer.Option(
        "testnet", help=f"Bybit simulation backend, one of {list(VALID_PAPER_BACKENDS)}."
    ),
) -> None:
    try:
        mode = resolve_trading_mode(os.environ.get("TRADING_MODE", ""), env=os.environ)
    except (ValueError, LiveTradingBlockedError) as exc:
        raise typer.BadParameter(str(exc), param_hint="TRADING_MODE") from exc
    if mode is not TradingMode.PAPER:
        raise typer.BadParameter(
            f"scripts/run_paper_session.py requires TRADING_MODE=PAPER, got {mode.value}",
            param_hint="TRADING_MODE",
        )
    if backend not in VALID_PAPER_BACKENDS:
        raise typer.BadParameter(
            f"backend must be one of {VALID_PAPER_BACKENDS}, got {backend!r}",
            param_hint="--backend",
        )

    universe = load_symbol_universe()
    try:
        universe.validate_symbol(symbol)
        universe.validate_timeframe(timeframe)
    except ValueError as exc:
        raise typer.BadParameter(str(exc)) from exc
    if strategy not in ALL_STRATEGIES:
        raise typer.BadParameter(
            f"unknown strategy {strategy!r}, expected one of {list(ALL_STRATEGIES)}",
            param_hint="--strategy",
        )
    if timeframe not in _TIMEFRAME_TO_BAR_AGGREGATION:
        raise typer.BadParameter(f"unsupported timeframe {timeframe!r} for live bars")

    instrument_id = live_instrument_id_for(symbol)
    step, aggregation = _TIMEFRAME_TO_BAR_AGGREGATION[timeframe]
    bar_type = BarType(
        instrument_id,
        BarSpecification(step, aggregation, PriceType.LAST),
        AggregationSource.EXTERNAL,
    )

    strategy_cls, config_cls = ALL_STRATEGIES[strategy]
    config = config_cls(instrument_id=instrument_id, bar_type=bar_type)
    strategy_instance = strategy_cls(config)
    recorder = SessionRecorder()
    strategy_instance.session_recorder = recorder

    session_id = f"{strategy}-{symbol}-{timeframe}"
    log.info("starting supervised paper trading session", session_id=session_id, backend=backend)

    node = build_paper_trading_node(strategy_instance, trading_mode=mode, backend=backend)
    supervisor = PaperSessionSupervisor(
        SupervisorConfig(max_restarts=max_restarts, backoff_seconds=backoff_seconds),
        checkpoint_path=Path(checkpoint_path),
        session_id=session_id,
    )
    try:
        state = supervisor.run(node.run, fill_summary_fn=recorder.summary)
    finally:
        node.dispose()

    log.info(
        "paper session finished",
        session_id=session_id,
        restart_count=state.restart_count,
        fill_summary=state.fill_summary,
    )


if __name__ == "__main__":
    app()
