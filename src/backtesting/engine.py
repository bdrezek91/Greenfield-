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
from nautilus_trader.model.currencies import USD
from nautilus_trader.model.enums import AccountType, OmsType
from nautilus_trader.model.instruments import CryptoPerpetual
from nautilus_trader.model.objects import Money
from nautilus_trader.trading.strategy import Strategy

from src.backtesting.costs import ExecutionAssumptions
from src.backtesting.data_adapter import klines_to_bars
from src.backtesting.instruments import (
    KRAKEN_VENUE,
    build_crypto_perpetual,
    load_instrument_specs,
)
from src.data.storage import read_klines


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


def build_engine(spec: BacktestRunSpec) -> tuple[BacktestEngine, dict[str, CryptoPerpetual]]:
    """Build a BacktestEngine with venue, instruments, and bar data loaded.

    No strategy is attached - callers add one (or none) with `engine.add_strategy`.
    Returns the engine and a symbol -> instrument map for convenience.
    """
    engine = BacktestEngine(
        config=BacktestEngineConfig(logging=LoggingConfig(log_level="ERROR"))
    )

    specs = load_instrument_specs()
    instruments = {symbol: build_crypto_perpetual(symbol, specs) for symbol in spec.symbols}

    engine.add_venue(
        venue=KRAKEN_VENUE,
        oms_type=OmsType.NETTING,
        account_type=AccountType.MARGIN,
        starting_balances=[Money(spec.starting_balance, USD)],
        base_currency=USD,
        default_leverage=specs.default_leverage,
        fee_model=spec.execution.fee_model(),
        fill_model=spec.execution.fill_model(),
    )

    for symbol, instrument in instruments.items():
        engine.add_instrument(instrument)

        df = read_klines(spec.data_dir, symbol, spec.timeframe, start=spec.start, end=spec.end)
        if df.empty:
            continue
        bars = klines_to_bars(df, instrument, spec.timeframe)
        engine.add_data(bars)

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
