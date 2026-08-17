"""FundingContrarian through the real NautilusTrader engine: a genuine
funding-rate outlier confirmed by rising open interest actually produces a
trade, and a flat/constant funding series (no positioning extreme at all)
produces none - the gate is real, not a no-op.
"""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path

import numpy as np
import pandas as pd

from src.backtesting.funding import FundingAssumptions
from src.backtesting.runner import run_backtest_window
from src.data.schema import COLUMNS
from src.data.storage import write_funding, write_klines, write_open_interest
from src.strategies.funding_contrarian import FundingContrarian, FundingContrarianConfig

_CONFIG_KWARGS = {
    "funding_zscore_lookback": 10,
    "funding_zscore_threshold": 1.5,
    "oi_confirmation_bars": 3,
    "oi_min_change_confirmation": 0.0,
}


def _write_bars(data_dir: Path, ts: pd.DatetimeIndex, close: np.ndarray) -> None:
    df = pd.DataFrame(
        {
            "timestamp": ts,
            "open": close,
            "high": close + close * 0.001,
            "low": close - close * 0.001,
            "close": close,
            "volume": 10.0,
            "turnover": 1000.0,
            "symbol": "BTCUSDT",
            "timeframe": "4h",
        }
    )[list(COLUMNS)]
    write_klines(df, data_dir)


def _write_open_interest_ramp(data_dir: Path, ts: pd.DatetimeIndex) -> None:
    # Steadily rising OI throughout - the confirmation condition (OI change
    # over oi_confirmation_bars > 0) is satisfied whenever there's history,
    # isolating the test to whether the funding z-score gate itself works.
    oi = 1_000_000.0 + np.arange(len(ts)) * 500.0
    write_open_interest(
        pd.DataFrame({"timestamp": ts, "symbol": "BTCUSDT", "open_interest": oi}), data_dir, "1h"
    )


def test_funding_outlier_with_rising_oi_produces_a_trade(tmp_path: Path) -> None:
    bar_ts = pd.date_range("2025-01-01", periods=200, freq="4h", tz="UTC")
    rng = np.random.default_rng(3)
    close = 60000 + np.cumsum(rng.normal(0, 20, size=len(bar_ts)))
    _write_bars(tmp_path, bar_ts, close)

    funding_ts = pd.date_range("2025-01-01", periods=60, freq="8h", tz="UTC")
    funding_rate = np.full(len(funding_ts), 0.0001)
    # A single, large positioning-extreme outlier partway through - crowded
    # longs paying heavily - is the contrarian trigger (-> expect a SELL).
    funding_rate[20] = 0.02
    write_funding(
        pd.DataFrame({"timestamp": funding_ts, "symbol": "BTCUSDT", "funding_rate": funding_rate}),
        tmp_path,
    )
    oi_ts = pd.date_range("2025-01-01", periods=len(bar_ts) * 4, freq="1h", tz="UTC")
    _write_open_interest_ramp(tmp_path, oi_ts)

    result = run_backtest_window(
        strategy_cls=FundingContrarian,
        config_cls=FundingContrarianConfig,
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


def test_constant_funding_rate_produces_no_trades(tmp_path: Path) -> None:
    """Zero variance in funding_rate means the z-score is undefined
    (std == 0) - the strategy must refuse to trade rather than divide by
    zero or treat a flat series as an extreme."""
    bar_ts = pd.date_range("2025-01-01", periods=200, freq="4h", tz="UTC")
    rng = np.random.default_rng(9)
    close = 60000 + np.cumsum(rng.normal(0, 20, size=len(bar_ts)))
    _write_bars(tmp_path, bar_ts, close)

    funding_ts = pd.date_range("2025-01-01", periods=60, freq="8h", tz="UTC")
    write_funding(
        pd.DataFrame({"timestamp": funding_ts, "symbol": "BTCUSDT", "funding_rate": 0.0001}),
        tmp_path,
    )
    oi_ts = pd.date_range("2025-01-01", periods=len(bar_ts) * 4, freq="1h", tz="UTC")
    _write_open_interest_ramp(tmp_path, oi_ts)

    result = run_backtest_window(
        strategy_cls=FundingContrarian,
        config_cls=FundingContrarianConfig,
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
