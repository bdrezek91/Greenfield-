"""CLI to run the momentum entry rule live against Kraken's demo (paper
trading) environment, via src.execution.live_runner.LiveRunner.

Requires TRADING_MODE=PAPER (see src/execution/mode.py - this is the only
mode this script accepts; LIVE requires its own explicit confirmation flag
and there is deliberately no scripts/live_trade.py - see
docs/LIVE_READINESS_CHECKLIST.md).

Only the momentum entry rule (src.strategies.signals.momentum_signal) runs
live so far - src.strategies.registry's other families (breakout,
volatility_expansion, mean_reversion, ...) still only run inside
NautilusTrader's BacktestEngine. Porting them to LiveRunner is a natural
follow-up once this path is verified end to end (see
docs/PROJECT_STATUS.md's Known Issues).

NOT VERIFIED IN THIS SESSION: this session's network egress policy blocks
kraken.com (see docs/DATA.md and src/execution/kraken_adapter.py's module
docstring). No order has actually been submitted through this path here.

Usage:
    export TRADING_MODE=PAPER
    export KRAKEN_API_KEY=...      # demo-environment key, see .env.example
    export KRAKEN_API_SECRET=...
    python scripts/paper_trade.py --symbol BTCUSD --timeframe 1h \
        --risk-per-trade 0.01 --max-portfolio-risk 0.05
"""

from __future__ import annotations

import os
import time

import pandas as pd
import structlog
import typer

from src.backtesting.instruments import build_crypto_perpetual, load_instrument_specs
from src.data.config import load_symbol_universe
from src.data.kraken_client import KrakenKlineClient
from src.execution.kraken_adapter import KrakenExecutionAdapter
from src.execution.live_runner import LiveBar, LiveRunner, LiveRunnerConfig
from src.execution.mode import LiveTradingBlockedError, TradingMode, resolve_trading_mode
from src.risk.engine import RiskConfig, RiskEngine

log = structlog.get_logger()
app = typer.Typer(add_completion=False)


@app.command()
def paper_trade(
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
) -> None:
    try:
        mode = resolve_trading_mode(os.environ.get("TRADING_MODE", ""), env=os.environ)
    except (ValueError, LiveTradingBlockedError) as exc:
        raise typer.BadParameter(str(exc), param_hint="TRADING_MODE") from exc
    if mode is not TradingMode.PAPER:
        raise typer.BadParameter(
            f"scripts/paper_trade.py requires TRADING_MODE=PAPER, got {mode.value}",
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
        # Reuses the execution adapter's own ccxt connection for this
        # authenticated balance call, rather than opening a second one -
        # not part of the ExecutionAdapter Protocol itself (that's
        # submit() only).
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

    log.info("starting paper trading session", symbol=symbol, timeframe=timeframe)
    last_ts_ms: int | None = None
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


if __name__ == "__main__":
    app()
