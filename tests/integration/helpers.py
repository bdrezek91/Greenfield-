"""Shared helpers for integration tests that run a strategy through the real
NautilusTrader backtest engine on synthetic, deterministic price series.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

from src.backtesting.data_adapter import bar_type_for
from src.backtesting.engine import BacktestRunSpec, build_engine
from src.data.schema import COLUMNS
from src.data.storage import write_klines


def write_synthetic_klines(
    data_dir: Path, close: np.ndarray, symbol: str = "BTCUSD"
) -> pd.DatetimeIndex:
    ts = pd.date_range("2024-01-01", periods=len(close), freq="1h", tz="UTC")
    df = pd.DataFrame(
        {
            "timestamp": ts,
            "open": close,
            "high": close + 0.5,
            "low": close - 0.5,
            "close": close,
            "volume": 10.0,
            "turnover": 1000.0,
            "symbol": symbol,
            "timeframe": "1h",
        }
    )[list(COLUMNS)]
    write_klines(df, data_dir)
    return ts


def run_strategy(tmp_path: Path, close: np.ndarray, strategy_cls, config_cls, **config_kwargs):
    ts = write_synthetic_klines(tmp_path, close)
    spec = BacktestRunSpec(
        symbols=["BTCUSD"], timeframe="1h", start=ts[0], end=ts[-1], data_dir=tmp_path
    )
    engine, instruments = build_engine(spec)
    instrument = instruments["BTCUSD"]
    bar_type = bar_type_for(instrument, "1h")
    config = config_cls(instrument_id=instrument.id, bar_type=bar_type, **config_kwargs)
    engine.add_strategy(strategy_cls(config))
    engine.run()
    positions = engine.trader.generate_positions_report()
    account = engine.trader.generate_account_report(next(iter(engine.list_venues())))
    engine.dispose()
    return positions, account
