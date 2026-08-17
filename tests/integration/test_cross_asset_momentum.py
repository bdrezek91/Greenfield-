"""CrossAssetMomentum through the real NautilusTrader engine: two
instruments loaded into one run (src.backtesting.runner's
reference_symbol wiring), the regime gate actually blocking/allowing
trades, and funding/mark-to-market applied to the traded (target) symbol.
"""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path

import numpy as np
import pandas as pd

from src.backtesting.funding import FundingAssumptions
from src.backtesting.runner import run_backtest_window
from src.data.schema import COLUMNS
from src.data.storage import write_klines
from src.strategies.cross_asset_momentum import CrossAssetMomentum, CrossAssetMomentumConfig


def _write_two_symbols(data_dir: Path, btc_close, eth_close, ts: pd.DatetimeIndex) -> None:
    for symbol, close in [("BTCUSDT", btc_close), ("ETHUSDT", eth_close)]:
        df = pd.DataFrame(
            {
                "timestamp": ts,
                "open": close,
                "high": close + close * 0.001,
                "low": close - close * 0.001,
                "close": close,
                "volume": 10.0,
                "turnover": 1000.0,
                "symbol": symbol,
                "timeframe": "4h",
            }
        )[list(COLUMNS)]
        write_klines(df, data_dir)


def test_regime_confirmation_allows_trades_in_a_clear_trend(tmp_path: Path) -> None:
    rng = np.random.default_rng(5)
    ts = pd.date_range("2025-01-01", "2025-08-01", freq="4h", tz="UTC")
    n = len(ts)
    btc_close = 60000 + np.arange(n) * 15 + rng.normal(0, 30, size=n)
    eth_close = 3000 + np.arange(n) * 1.2 + rng.normal(0, 3, size=n)
    _write_two_symbols(tmp_path, btc_close, eth_close, ts)

    result = run_backtest_window(
        strategy_cls=CrossAssetMomentum,
        config_cls=CrossAssetMomentumConfig,
        symbol="ETHUSDT",
        timeframe="4h",
        start=ts[0],
        end=ts[-1],
        data_dir=tmp_path,
        starting_balance=Decimal(100_000),
        periods_per_year=2191.5,
        config_kwargs={"lookback_bars": 10, "threshold": 0.005},
        funding_assumptions=FundingAssumptions(),
        reference_symbol="BTCUSDT",
    )

    assert result.metrics.trade_metrics.trades > 0
    assert result.funding_applied is True


def test_regime_gate_blocks_trades_on_pure_noise(tmp_path: Path) -> None:
    """A random walk with no persistent trend rarely satisfies both "own
    momentum signal fires" AND "reference is in a confirming ADX-trending
    regime" at once - the gate should keep trade count low/zero, not fire
    on every momentum signal like the ungated Momentum strategy would."""
    rng = np.random.default_rng(11)
    ts = pd.date_range("2025-01-01", "2025-06-01", freq="4h", tz="UTC")
    n = len(ts)
    btc_close = 60000 + np.cumsum(rng.normal(0, 30, size=n))
    eth_close = 3000 + np.cumsum(rng.normal(0, 3, size=n))
    _write_two_symbols(tmp_path, btc_close, eth_close, ts)

    result = run_backtest_window(
        strategy_cls=CrossAssetMomentum,
        config_cls=CrossAssetMomentumConfig,
        symbol="ETHUSDT",
        timeframe="4h",
        start=ts[0],
        end=ts[-1],
        data_dir=tmp_path,
        starting_balance=Decimal(100_000),
        periods_per_year=2191.5,
        config_kwargs={"lookback_bars": 10, "threshold": 0.01},
        funding_assumptions=FundingAssumptions(),
        reference_symbol="BTCUSDT",
    )

    # Not a precise bound - just confirms the gate is meaningfully
    # restrictive, not a no-op that trades on every base momentum signal.
    assert result.metrics.trade_metrics.trades < 50


def test_missing_reference_data_is_not_validated_at_this_layer(tmp_path: Path) -> None:
    """Documents a real gap, not a guarantee: run_backtest_window (like
    build_engine underneath it) does not check that a symbol's data
    exists - a missing reference symbol silently produces an instrument
    with zero bars, so the regime gate in CrossAssetMomentum never
    confirms and the strategy quietly trades nothing, rather than
    erroring. Data-completeness validation is the orchestrator's job
    (src/research/orchestrator.py must check the reference symbol's data
    too, not just the target's, before trusting a 0-trade or low-trade
    result) - never this lower-level primitive's, which validates
    nothing about any of its inputs by design (see its own docstring)."""
    rng = np.random.default_rng(2)
    ts = pd.date_range("2025-01-01", "2025-03-01", freq="4h", tz="UTC")
    eth_close = 3000 + np.cumsum(rng.normal(0, 3, size=len(ts)))
    df = pd.DataFrame(
        {
            "timestamp": ts,
            "open": eth_close,
            "high": eth_close + 3,
            "low": eth_close - 3,
            "close": eth_close,
            "volume": 10.0,
            "turnover": 1000.0,
            "symbol": "ETHUSDT",
            "timeframe": "4h",
        }
    )[list(COLUMNS)]
    write_klines(df, tmp_path)
    # BTCUSDT data deliberately not written.

    result = run_backtest_window(
        strategy_cls=CrossAssetMomentum,
        config_cls=CrossAssetMomentumConfig,
        symbol="ETHUSDT",
        timeframe="4h",
        start=ts[0],
        end=ts[-1],
        data_dir=tmp_path,
        starting_balance=Decimal(100_000),
        periods_per_year=2191.5,
        config_kwargs={"lookback_bars": 10, "threshold": 0.01},
        reference_symbol="BTCUSDT",
    )
    assert result.metrics.trade_metrics.trades == 0
