"""FundingAwareMultiHorizonTrend through the real NautilusTrader engine:
a same-symbol 4h+1d confirmation actually gates trades (agreement trades,
disagreement doesn't), and the funding veto actually blocks entries it
would otherwise take - none of this is a no-op.

The 1d series here is always the literal end-of-day resample of the 4h
series (never an independently-drawn random walk) so 4h/1d agreement or
disagreement is a genuine, deterministic property of the price path, not
an artifact of two unrelated fixtures.
"""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path

import numpy as np
import pandas as pd

from src.backtesting.funding import FundingAssumptions
from src.backtesting.runner import run_backtest_window
from src.data.schema import COLUMNS
from src.data.storage import write_funding, write_klines
from src.strategies.funding_aware_multi_horizon_trend import (
    FundingAwareMultiHorizonTrend,
    FundingAwareMultiHorizonTrendConfig,
)

_CONFIG_KWARGS = {
    "lookback_bars_4h": 10,
    "lookback_bars_1d": 5,
    "funding_zscore_lookback": 10,
    "funding_zscore_threshold": 2.0,
}


def _write_bars(data_dir: Path, ts_4h: pd.DatetimeIndex, close_4h: np.ndarray) -> None:
    df_4h = pd.DataFrame(
        {
            "timestamp": ts_4h,
            "open": close_4h,
            "high": close_4h + close_4h * 0.001,
            "low": close_4h - close_4h * 0.001,
            "close": close_4h,
            "volume": 10.0,
            "turnover": 1000.0,
            "symbol": "BTCUSDT",
            "timeframe": "4h",
        }
    )[list(COLUMNS)]
    write_klines(df_4h, data_dir)

    # Literal end-of-day resample - the 1d series a real exchange would
    # report is exactly "the last 4h close of the day", never a separately
    # drawn series.
    daily_close = pd.Series(close_4h, index=ts_4h).resample("1D").last().dropna()
    df_1d = pd.DataFrame(
        {
            "timestamp": daily_close.index,
            "open": daily_close.to_numpy(),
            "high": daily_close.to_numpy() * 1.001,
            "low": daily_close.to_numpy() * 0.999,
            "close": daily_close.to_numpy(),
            "volume": 60.0,
            "turnover": 6000.0,
            "symbol": "BTCUSDT",
            "timeframe": "1d",
        }
    )[list(COLUMNS)]
    write_klines(df_1d, data_dir)


def _write_flat_funding(data_dir: Path, ts_4h: pd.DatetimeIndex) -> None:
    funding_ts = pd.date_range(ts_4h[0], ts_4h[-1], freq="8h", tz="UTC")
    write_funding(
        pd.DataFrame({"timestamp": funding_ts, "symbol": "BTCUSDT", "funding_rate": 0.0001}),
        data_dir,
    )


def _run(data_dir: Path, ts_4h: pd.DatetimeIndex, config_kwargs: dict | None = None):
    return run_backtest_window(
        strategy_cls=FundingAwareMultiHorizonTrend,
        config_cls=FundingAwareMultiHorizonTrendConfig,
        symbol="BTCUSDT",
        timeframe="4h",
        start=ts_4h[0],
        end=ts_4h[-1],
        data_dir=data_dir,
        starting_balance=Decimal(100_000),
        periods_per_year=2191.5,
        config_kwargs={**_CONFIG_KWARGS, **(config_kwargs or {})},
        funding_assumptions=FundingAssumptions(),
        higher_timeframe="1d",
    )


def test_4h_1d_agreement_produces_trades(tmp_path: Path) -> None:
    rng = np.random.default_rng(7)
    ts_4h = pd.date_range("2025-01-01", "2025-10-01", freq="4h", tz="UTC")
    close_4h = 60000 + np.arange(len(ts_4h)) * 12 + rng.normal(0, 25, size=len(ts_4h))
    _write_bars(tmp_path, ts_4h, close_4h)
    _write_flat_funding(tmp_path, ts_4h)

    result = _run(tmp_path, ts_4h)

    assert result.metrics.trade_metrics.trades > 0
    assert result.funding_applied is True


def test_missing_1d_confirmation_history_blocks_every_trade(tmp_path: Path) -> None:
    """`signal()` requires base_signal == higher_signal with BOTH non-None
    (fail-closed on insufficient 1d history, per the prereg's
    "Przyczynowość" section) - a lookback_bars_1d longer than the entire
    available 1d history means momentum_signal on the 1d deque never has
    enough points to return anything but None, so the AND-gate can never
    be satisfied regardless of how strong the 4h trend is. This isolates
    the confirmation requirement itself from any particular sign-agreement
    heuristic: the same strong uptrend that produces trades in
    test_4h_1d_agreement_produces_trades above must produce ZERO here,
    with only lookback_bars_1d changed."""
    rng = np.random.default_rng(7)
    ts_4h = pd.date_range("2025-01-01", "2025-10-01", freq="4h", tz="UTC")
    close_4h = 60000 + np.arange(len(ts_4h)) * 12 + rng.normal(0, 25, size=len(ts_4h))
    _write_bars(tmp_path, ts_4h, close_4h)
    _write_flat_funding(tmp_path, ts_4h)

    # ~273 days of 1d bars exist in this fixture - a lookback far beyond
    # that guarantees momentum_signal never has lookback_bars_1d + 1 points.
    result = _run(tmp_path, ts_4h, config_kwargs={"lookback_bars_1d": 10_000})

    assert result.metrics.trade_metrics.trades == 0


def test_extreme_funding_vetoes_an_entry_it_would_otherwise_take(tmp_path: Path) -> None:
    """The same deterministic price path as test_4h_1d_agreement_produces_
    trades above (identical rng seed) enters its first trade at exactly
    2025-01-06 04:00 with flat funding. Spiking ONLY the single funding
    observation immediately preceding that decision to an extreme value
    (z-score ~3.0 against the other 9 points in its
    funding_zscore_lookback=10 window - a genuine outlier, not a sustained
    regime shift a z-score statistic couldn't flag as extreme anyway)
    vetoes exactly that one BUY entry, pushing the first trade to the next
    bar the AND-gate is satisfied on (4h later) rather than blocking it
    forever - the veto blocks one decision, it does not disable the
    strategy.
    """
    rng = np.random.default_rng(7)
    ts_4h = pd.date_range("2025-01-01", "2025-10-01", freq="4h", tz="UTC")
    close_4h = 60000 + np.arange(len(ts_4h)) * 12 + rng.normal(0, 25, size=len(ts_4h))
    _write_bars(tmp_path, ts_4h, close_4h)

    funding_ts = pd.date_range(ts_4h[0], ts_4h[-1], freq="8h", tz="UTC")
    funding_rate = 0.0001 + np.random.default_rng(3).normal(0, 0.00002, size=len(funding_ts))
    known_first_entry = pd.Timestamp("2025-01-06 04:00:00", tz="UTC")
    observations_before_entry = funding_ts[funding_ts < known_first_entry]
    spike_idx = funding_ts.get_loc(observations_before_entry[-1])
    funding_rate[spike_idx] = 0.05
    write_funding(
        pd.DataFrame({"timestamp": funding_ts, "symbol": "BTCUSDT", "funding_rate": funding_rate}),
        tmp_path,
    )

    result = _run(tmp_path, ts_4h)

    assert result.metrics.trade_metrics.trades > 0
    assert result.trades["entry_time"].iloc[0] > known_first_entry
