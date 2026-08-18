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
from src.backtesting.data_adapter import closed_klines, klines_to_bars, timeframe_delta
from src.backtesting.instruments import (
    BYBIT_VENUE,
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
    warmup_start: pd.Timestamp | None = None


def read_event_time_klines(
    data_dir: Path,
    symbol: str,
    timeframe: str,
    *,
    event_start: pd.Timestamp,
    event_end: pd.Timestamp,
) -> pd.DataFrame:
    """Read bars whose information-availability time is in ``[start, end)``.

    Canonical storage uses Bybit bar-open timestamps, while Nautilus receives
    completed external bars at bar close.  Converting the requested event-time
    range back to canonical open-time before reading makes adjacent windows
    genuinely non-overlapping.
    """
    delta = timeframe_delta(timeframe)
    canonical_start = event_start - delta
    canonical_end = event_end - delta
    df = read_klines(
        data_dir,
        symbol,
        timeframe,
        start=canonical_start,
        end=canonical_end,
    )
    if df.empty:
        return df
    event_times = pd.to_datetime(df["timestamp"], utc=True) + delta
    return df.loc[(event_times >= event_start) & (event_times < event_end)].reset_index(drop=True)


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
        venue=BYBIT_VENUE,
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

        load_start = spec.warmup_start or spec.start
        df = read_event_time_klines(
            spec.data_dir,
            symbol,
            spec.timeframe,
            event_start=load_start,
            event_end=spec.end,
        )
        # Defensive availability check.  ``read_event_time_klines`` already
        # enforces event_time < end; this additionally rejects malformed
        # trailing input whose close is not actually available.
        df = closed_klines(df, spec.timeframe, spec.end)
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
