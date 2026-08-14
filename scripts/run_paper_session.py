"""CLI: run the momentum entry rule live against Kraken's demo environment
as a long-running, supervised paper-trading session (Phase 14) - the
durable counterpart to scripts/paper_trade.py's single unsupervised
polling loop.

Adds, on top of scripts/paper_trade.py:
  - src/execution/supervisor.py: the polling loop is retried with
    exponential backoff on failure (e.g. a demo-environment disconnect),
    instead of the whole process dying on the first one.
  - src/execution/session_state.py: session metadata (restart count, last
    error, latest fill summary) is checkpointed to `--checkpoint-path` so
    the session's operational history survives a full process restart,
    not just an in-process retry.
  - src.execution.fill_tracking.FillTracker (via LiveRunner.tracker) - the
    section-32 expected-vs-actual fill comparison, fed by this live run.

NOT VERIFIED IN THIS SESSION - same network egress restriction to
kraken.com documented in src/execution/kraken_adapter.py's module
docstring. Validate on a machine with unrestricted network access before
relying on this for a real long-running session.

Usage:
    export TRADING_MODE=PAPER
    export KRAKEN_API_KEY=...      # demo-environment key, see .env.example
    export KRAKEN_API_SECRET=...
    python scripts/run_paper_session.py --symbol BTCUSD --timeframe 1h \
        --checkpoint-path reports/paper_session.json
"""

from __future__ import annotations

import os
import time
from pathlib import Path

import pandas as pd
import structlog
import typer

from src.backtesting.instruments import build_crypto_perpetual, load_instrument_specs
from src.data.config import load_symbol_universe
from src.data.kraken_client import KrakenKlineClient
from src.execution.kraken_adapter import KrakenExecutionAdapter
from src.execution.live_runner import LiveBar, LiveRunner, LiveRunnerConfig
from src.execution.mode import LiveTradingBlockedError, TradingMode, resolve_trading_mode
from src.execution.supervisor import PaperSessionSupervisor, SupervisorConfig
from src.risk.engine import RiskConfig, RiskEngine

log = structlog.get_logger()
app = typer.Typer(add_completion=False)


@app.command()
def run(
    symbol: str = typer.Option(..., help="Single symbol, e.g. BTCUSD."),
    timeframe: str = typer.Option("1h", help="Timeframe, e.g. 1h."),
    holding_period_bars: int = typer.Option(24, help="Bars to hold before exiting."),
    momentum_lookback_bars: int = typer.Option(10, help="Momentum signal lookback."),
    momentum_threshold: float = typer.Option(0.01, help="Minimum fractional change to enter."),
    risk_per_trade: float = typer.Option(0.01, help="Fraction of equity risked per trade."),
    max_portfolio_risk: float = typer.Option(0.05, help="Cap on total committed risk fraction."),
    max_daily_loss: float = typer.Option(0.03, help="Fraction of equity; halts new entries."),
    max_drawdown: float = typer.Option(0.25, help="Fraction below peak equity; halts entries."),
    max_leverage: float = typer.Option(3.0, help="Cap on notional / equity."),
    poll_seconds: float = typer.Option(60.0, help="How often to check for a new closed bar."),
    checkpoint_path: str = typer.Option(
        "reports/paper_session.json", help="Where to persist session state across restarts."
    ),
    max_restarts: int = typer.Option(5, help="Give up after this many consecutive failures."),
    backoff_seconds: float = typer.Option(30.0, help="Initial retry backoff."),
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

    universe = load_symbol_universe()
    try:
        universe.validate_symbol(symbol)
        universe.validate_timeframe(timeframe)
    except ValueError as exc:
        raise typer.BadParameter(str(exc)) from exc

    api_key = os.environ.get("KRAKEN_API_KEY", "")
    api_secret = os.environ.get("KRAKEN_API_SECRET", "")
    if not api_key or not api_secret:
        raise typer.BadParameter("KRAKEN_API_KEY and KRAKEN_API_SECRET must be set")

    specs = load_instrument_specs()
    instrument = build_crypto_perpetual(symbol, specs)
    risk_engine = RiskEngine(
        RiskConfig(
            risk_per_trade=risk_per_trade,
            max_portfolio_risk=max_portfolio_risk,
            max_daily_loss=max_daily_loss,
            max_drawdown=max_drawdown,
            max_leverage=max_leverage,
        )
    )
    adapter = KrakenExecutionAdapter(mode, api_key, api_secret)
    kline_client = KrakenKlineClient()

    def equity_fn() -> float:
        balance = adapter.transport.fetch_balance()  # type: ignore[attr-defined]
        return float(balance.get("USD", {}).get("total", 0.0))

    runner = LiveRunner(
        config=LiveRunnerConfig(
            symbol=symbol,
            holding_period_bars=holding_period_bars,
            momentum_lookback_bars=momentum_lookback_bars,
            momentum_threshold=momentum_threshold,
        ),
        instrument=instrument,
        risk_engine=risk_engine,
        execution_adapter=adapter,
        equity_fn=equity_fn,
    )

    session_id = f"momentum-{symbol}-{timeframe}"
    log.info("starting supervised paper trading session", session_id=session_id)

    last_ts_ms: int | None = None

    def poll_forever() -> None:
        nonlocal last_ts_ms
        while True:
            rows = kline_client.get_kline_page(symbol=symbol, interval=timeframe, limit=2)
            if rows:
                ts_ms, _, _, _, close, _, _ = rows[-1]
                ts_ms_int = int(ts_ms)
                if last_ts_ms is None or ts_ms_int > last_ts_ms:
                    last_ts_ms = ts_ms_int
                    bar = LiveBar(
                        timestamp=pd.Timestamp(ts_ms_int, unit="ms", tz="UTC").to_pydatetime(),
                        close=float(close),
                    )
                    runner.on_bar(bar)
                    log.info(
                        "bar processed",
                        timestamp=bar.timestamp.isoformat(),
                        close=bar.close,
                        is_flat=runner.is_flat,
                    )
            time.sleep(poll_seconds)

    supervisor = PaperSessionSupervisor(
        SupervisorConfig(max_restarts=max_restarts, backoff_seconds=backoff_seconds),
        checkpoint_path=Path(checkpoint_path),
        session_id=session_id,
    )
    state = supervisor.run(poll_forever, fill_summary_fn=runner.tracker.summary)

    log.info(
        "paper session finished",
        session_id=session_id,
        restart_count=state.restart_count,
        fill_summary=state.fill_summary,
    )


if __name__ == "__main__":
    app()
