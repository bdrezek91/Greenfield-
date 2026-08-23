"""Assemble and run a NautilusTrader BacktestEngine against our Parquet klines.

This module deliberately does not import or require any strategy. Per
docs/PHASE_0_ARCHITECTURE_RESEARCH.md, strategy families are a Phase 5+
concern - Phase 3 only has to prove that data, instrument, venue, and cost
configuration wire up correctly end to end.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from pathlib import Path

import pandas as pd
from nautilus_trader.backtest.engine import BacktestEngine, BacktestEngineConfig
from nautilus_trader.config import LoggingConfig
from nautilus_trader.model.currencies import USDT
from nautilus_trader.model.enums import AccountType, OmsType
from nautilus_trader.model.instruments import CryptoPerpetual
from nautilus_trader.model.objects import Money
from nautilus_trader.trading.strategy import Strategy

from src.backtesting.costs import ExecutionAssumptions
from src.backtesting.data_adapter import klines_to_bars
from src.backtesting.instruments import (
    build_crypto_perpetual,
    load_instrument_specs,
    venue_for_exchange,
)
from src.data.binance_klines_storage import read_binance_klines
from src.data.storage import read_klines

_KLINE_READERS = {
    "bybit": read_klines,
    "binance": read_binance_klines,
}


def _read_klines(
    exchange: str,
    data_dir: Path,
    symbol: str,
    timeframe: str,
    *,
    start: pd.Timestamp | None = None,
    end: pd.Timestamp | None = None,
) -> pd.DataFrame:
    if exchange not in _KLINE_READERS:
        raise ValueError(
            f"unsupported exchange {exchange!r}, expected one of {tuple(_KLINE_READERS)}"
        )
    return _KLINE_READERS[exchange](data_dir, symbol, timeframe, start=start, end=end)


@dataclass(frozen=True)
class BacktestRunSpec:
    """Everything needed to reproduce a run - mirrors the experiment metadata
    fields required by docs/RESEARCH_METHODOLOGY.md.
    """

    symbols: list[str]
    timeframe: str
    start: pd.Timestamp
    end: pd.Timestamp
    data_dir: Path
    starting_balance: Decimal = Decimal(100_000)
    execution: ExecutionAssumptions = field(default_factory=ExecutionAssumptions)
    # If set, a second timeframe of `symbols[0]` (the primary traded
    # symbol only, never a reference symbol) is also loaded into the same
    # engine run - for a strategy that needs a higher-timeframe confirming
    # signal on the SAME instrument (src.strategies.
    # funding_aware_multi_horizon_trend), as distinct from a reference
    # symbol, which is a DIFFERENT instrument at the same timeframe.
    higher_timeframe: str | None = None
    # Default "bybit" preserves every existing caller's exact prior
    # behavior. "binance" reads from src.data.binance_klines_storage and
    # uses configs/instruments_binance.yaml - see
    # src/backtesting/instruments.py's module docstring and
    # docs/CLAUDE_CODE_CONTINUATION.md's Cycle 25 section.
    exchange: str = "bybit"


def build_engine(spec: BacktestRunSpec) -> tuple[BacktestEngine, dict[str, CryptoPerpetual]]:
    """Build a BacktestEngine with venue, instruments, and bar data loaded.

    No strategy is attached - callers add one (or none) with `engine.add_strategy`.
    Returns the engine and a symbol -> instrument map for convenience.
    """
    engine = BacktestEngine(
        config=BacktestEngineConfig(logging=LoggingConfig(log_level="ERROR"))
    )

    specs = load_instrument_specs(exchange=spec.exchange)
    instruments = {
        symbol: build_crypto_perpetual(symbol, specs, exchange=spec.exchange)
        for symbol in spec.symbols
    }

    engine.add_venue(
        venue=venue_for_exchange(spec.exchange),
        oms_type=OmsType.NETTING,
        account_type=AccountType.MARGIN,
        starting_balances=[Money(spec.starting_balance, USDT)],
        base_currency=USDT,
        default_leverage=specs.default_leverage,
        fee_model=spec.execution.fee_model(),
        fill_model=spec.execution.fill_model(),
    )

    for symbol, instrument in instruments.items():
        engine.add_instrument(instrument)

        df = _read_klines(
            spec.exchange, spec.data_dir, symbol, spec.timeframe, start=spec.start, end=spec.end
        )
        if df.empty:
            continue
        bars = klines_to_bars(df, instrument, spec.timeframe)
        engine.add_data(bars)

    if spec.higher_timeframe is not None:
        primary_symbol = spec.symbols[0]
        primary_instrument = instruments[primary_symbol]
        higher_df = _read_klines(
            spec.exchange,
            spec.data_dir,
            primary_symbol,
            spec.higher_timeframe,
            start=spec.start,
            end=spec.end,
        )
        if not higher_df.empty:
            higher_bars = klines_to_bars(higher_df, primary_instrument, spec.higher_timeframe)
            engine.add_data(higher_bars)

    return engine, instruments


def run_backtest(spec: BacktestRunSpec, strategy: Strategy | None = None) -> BacktestEngine:
    """Run a backtest per `spec`, optionally with a single strategy attached.

    With `strategy=None` this validates the full data/instrument/venue/cost
    plumbing while generating zero orders - the Phase 3 acceptance case.
    """
    engine, _ = build_engine(spec)
    if strategy is not None:
        engine.add_strategy(strategy)
    engine.run()
    return engine
