"""LiquiditySweepConfluence through the real NautilusTrader engine: a
genuine liquidity sweep (wick beyond the prior range, close back inside)
confirmed by rising open interest produces a trade, and a flat/no-wick
price series (no sweep ever possible) produces none - the gate is real.
"""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path

import numpy as np
import pandas as pd

from src.backtesting.funding import FundingAssumptions
from src.backtesting.runner import run_backtest_window
from src.data.schema import COLUMNS
from src.data.storage import write_klines, write_open_interest
from src.strategies.liquidity_sweep_confluence import (
    LiquiditySweepConfluence,
    LiquiditySweepConfluenceConfig,
)

_CONFIG_KWARGS = {"structure_lookback": 5, "oi_confirmation_bars": 3}


def _write_bars(data_dir: Path, ts: pd.DatetimeIndex, high, low, close) -> None:
    df = pd.DataFrame(
        {
            "timestamp": ts,
            "open": close,
            "high": high,
            "low": low,
            "close": close,
            "volume": 10.0,
            "turnover": 1000.0,
            "symbol": "BTCUSDT",
            "timeframe": "4h",
        }
    )[list(COLUMNS)]
    write_klines(df, data_dir)


def _write_oi_ramp(data_dir: Path, ts: pd.DatetimeIndex) -> None:
    oi = 1_000_000.0 + np.arange(len(ts)) * 500.0
    write_open_interest(
        pd.DataFrame({"timestamp": ts, "symbol": "BTCUSDT", "open_interest": oi}), data_dir, "1h"
    )


def test_liquidity_sweep_with_rising_oi_produces_a_trade(tmp_path: Path) -> None:
    bar_ts = pd.date_range("2025-01-01", periods=60, freq="4h", tz="UTC")
    n = len(bar_ts)
    # Flat, wick-less warmup (prior_high = prior_low = 100 once the
    # 5-bar structure window is full) - then one bar whose high sweeps
    # above 100 but closes back below it (a failed breakout -> SELL).
    high = np.full(n, 100.0)
    low = np.full(n, 100.0)
    close = np.full(n, 100.0)
    sweep_idx = 10
    high[sweep_idx] = 105.0
    low[sweep_idx] = 99.0
    close[sweep_idx] = 99.5
    _write_bars(tmp_path, bar_ts, high, low, close)
    oi_ts = pd.date_range("2025-01-01", periods=n * 4, freq="1h", tz="UTC")
    _write_oi_ramp(tmp_path, oi_ts)

    result = run_backtest_window(
        strategy_cls=LiquiditySweepConfluence,
        config_cls=LiquiditySweepConfluenceConfig,
        symbol="BTCUSDT",
        timeframe="4h",
        start=bar_ts[0],
        end=bar_ts[-1],
        data_dir=tmp_path,
        starting_balance=Decimal(100_000),
        periods_per_year=2191.5,
        config_kwargs=_CONFIG_KWARGS,
        funding_assumptions=FundingAssumptions(),
    )

    assert result.metrics.trade_metrics.trades > 0
    assert result.funding_applied is True


def test_no_wick_price_series_produces_no_trades(tmp_path: Path) -> None:
    """high == low == close every bar - a sweep (high > prior_high AND
    close < prior_high) can never be true regardless of trend, so this
    must trade zero times even though price moves a lot."""
    bar_ts = pd.date_range("2025-01-01", periods=60, freq="4h", tz="UTC")
    n = len(bar_ts)
    rng = np.random.default_rng(4)
    close = 100 + np.cumsum(rng.normal(0, 2, size=n))
    _write_bars(tmp_path, bar_ts, close, close, close)
    oi_ts = pd.date_range("2025-01-01", periods=n * 4, freq="1h", tz="UTC")
    _write_oi_ramp(tmp_path, oi_ts)

    result = run_backtest_window(
        strategy_cls=LiquiditySweepConfluence,
        config_cls=LiquiditySweepConfluenceConfig,
        symbol="BTCUSDT",
        timeframe="4h",
        start=bar_ts[0],
        end=bar_ts[-1],
        data_dir=tmp_path,
        starting_balance=Decimal(100_000),
        periods_per_year=2191.5,
        config_kwargs=_CONFIG_KWARGS,
        funding_assumptions=FundingAssumptions(),
    )

    assert result.metrics.trade_metrics.trades == 0
