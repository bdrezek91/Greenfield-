"""CLI to run one strategy live against a Bybit simulation backend
(paper trading) - either "testnet" or "demo", see
src/execution/paper_node.py's module docstring for the difference.

Requires TRADING_MODE=PAPER (see src/execution/mode.py - this is the only
mode this script accepts; LIVE is a different, not-yet-built path that
requires its own explicit confirmation flag and is out of scope here).

NOT VERIFIED IN THIS SESSION due to a network egress restriction to
api.bybit.com - see src/execution/paper_node.py's module docstring. Run
this only after validating connectivity on a machine with unrestricted
network access.

Usage:
    export TRADING_MODE=PAPER
    export BYBIT_API_KEY=...      # testnet key, see .env.example
    export BYBIT_API_SECRET=...
    python scripts/paper_trade.py --symbol BTCUSDT --timeframe 1h --strategy trend_following

    # or, against Demo Trading instead of testnet.bybit.com:
    export BYBIT_DEMO_API_KEY=...
    export BYBIT_DEMO_API_SECRET=...
    python scripts/paper_trade.py --symbol BTCUSDT --timeframe 1h \
        --strategy trend_following --backend demo

    # with non-default strategy parameters (e.g. from a walk-forward run):
    python scripts/paper_trade.py --symbol BTCUSDT --timeframe 4h \
        --strategy momentum --backend demo \
        --params '{"lookback_bars": 20, "threshold": 0.005}'
"""

from __future__ import annotations

import json
import os

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
from src.strategies.registry import ALL_STRATEGIES, build_registered_strategy

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
def paper_trade(
    symbol: str = typer.Option(..., help="Single symbol, e.g. BTCUSDT."),
    timeframe: str = typer.Option("1h", help="Timeframe, e.g. 1h."),
    strategy: str = typer.Option(..., help=f"One of {list(ALL_STRATEGIES)}."),
    backend: str = typer.Option(
        "testnet", help=f"Bybit simulation backend, one of {list(VALID_PAPER_BACKENDS)}."
    ),
    params: str | None = typer.Option(
        None, help='JSON dict of strategy config overrides, e.g. \'{"lookback_bars": 20}\'.'
    ),
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

    try:
        parsed_params = json.loads(params) if params else {}
    except json.JSONDecodeError as exc:
        raise typer.BadParameter(f"invalid JSON: {exc}", param_hint="--params") from exc

    strategy_instance = build_registered_strategy(
        strategy,
        instrument_id=instrument_id,
        bar_type=bar_type,
        params=parsed_params,
    )

    log.info(
        "starting paper trading session",
        symbol=symbol,
        timeframe=timeframe,
        strategy=strategy,
        backend=backend,
        params=parsed_params,
    )
    node = build_paper_trading_node(strategy_instance, trading_mode=mode, backend=backend)
    try:
        node.run()
    finally:
        node.dispose()


if __name__ == "__main__":
    app()
