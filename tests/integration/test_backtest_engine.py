"""End-to-end engine smoke test: data -> instrument -> venue -> costs -> run.

Deliberately runs with zero strategies attached (Phase 3 scope - strategy
families are Phase 5+). This proves the plumbing works: the account starts
at the configured balance and stays flat since nothing ever trades.
"""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path

import numpy as np
import pandas as pd

from src.backtesting.engine import BacktestRunSpec, run_backtest
from src.data.schema import COLUMNS
from src.data.storage import write_klines


def _write_synthetic_klines(data_dir: Path, symbol: str, n: int = 50) -> pd.DatetimeIndex:
    ts = pd.date_range("2024-01-01", periods=n, freq="1h", tz="UTC")
    rng = np.random.default_rng(0)
    close = 100 + np.cumsum(rng.normal(0, 0.5, size=n))
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


def test_engine_runs_end_to_end_with_no_strategy(tmp_path: Path) -> None:
    ts = _write_synthetic_klines(tmp_path, "BTCUSD")
    spec = BacktestRunSpec(
        symbols=["BTCUSD"],
        timeframe="1h",
        start=ts[0],
        end=ts[-1],
        data_dir=tmp_path,
        starting_balance=Decimal(100_000),
    )

    engine = run_backtest(spec)

    assert engine.run_finished is not None
    venue = next(iter(engine.list_venues()))
    account_report = engine.trader.generate_account_report(venue)
    assert not account_report.empty
    assert float(account_report["total"].iloc[0]) == 100_000.0

    # No strategy was attached, so nothing should ever have traded.
    assert engine.trader.generate_positions_report().empty
    assert engine.trader.generate_order_fills_report().empty


def test_engine_handles_multiple_symbols(tmp_path: Path) -> None:
    ts_btc = _write_synthetic_klines(tmp_path, "BTCUSD")
    _write_synthetic_klines(tmp_path, "ETHUSD")

    spec = BacktestRunSpec(
        symbols=["BTCUSD", "ETHUSD"],
        timeframe="1h",
        start=ts_btc[0],
        end=ts_btc[-1],
        data_dir=tmp_path,
    )

    engine = run_backtest(spec)
    assert engine.run_finished is not None


def test_engine_skips_symbol_with_no_data(tmp_path: Path) -> None:
    ts = _write_synthetic_klines(tmp_path, "BTCUSD")
    spec = BacktestRunSpec(
        symbols=["BTCUSD", "XRPUSD"],  # XRPUSD has no data on disk
        timeframe="1h",
        start=ts[0],
        end=ts[-1],
        data_dir=tmp_path,
    )

    engine = run_backtest(spec)
    assert engine.run_finished is not None
