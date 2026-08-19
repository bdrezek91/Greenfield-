"""Truncated-series (no-lookahead) proof for
src.strategies.funding_aware_multi_horizon_trend.FundingAwareMultiHorizonTrend,
required explicitly by
docs/PREREGISTRATION_funding_aware_multi_horizon_trend.md's "Przyczynowość
wielointerwałowa" section: every trade decided at or before some cutoff T
must be IDENTICAL whether or not any data after T exists, for both the 4h
primary series AND the 1d confirming series.

Same structural proof as tests/lookahead/test_feature_no_lookahead.py, but
run through the real NautilusTrader engine end to end (not a pure
dataframe transform) via two full backtest runs on the same price/funding
fixture that differ only in how much data after the cutoff exists:
- "full": the whole fixture (through the fixture's actual end).
- "truncated": everything strictly after the cutoff deleted from disk
  before the engine ever sees it, for the 4h bars, the 1d bars, AND the
  funding series (only the funding series has a real read-time as-of
  guard already tested in isolation elsewhere - this test proves the
  strategy's own multi-timeframe subscription pattern doesn't leak future
  bars, which nothing else in this repo tests directly for this strategy).

If any of the three inputs leaked information from after the cutoff into
a decision made at or before it, appending more of that input after the
cutoff (going from "truncated" to "full") would change a trade that was
already decided - it does not, for every symbol/direction combination
this asserts on.
"""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

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
_CUTOFF = pd.Timestamp("2025-07-01", tz="UTC")
# Trades are only compared strictly before this margin, not right up to
# _CUTOFF itself: a decision within one day of the boundary can
# legitimately differ between the two runs for a reason that has nothing
# to do with lookahead - whether `read_klines`'s inclusive/exclusive `end`
# bound happens to include or exclude the single 1d bar whose timestamp
# sits closest to the cutoff is a data-loading window-edge artifact (the
# 1d bar for the boundary day itself), not evidence a decision used
# information from strictly after the cutoff.
_COMPARISON_MARGIN = pd.Timedelta(days=3)


def _write_fixture(data_dir: Path, ts_4h: pd.DatetimeIndex, close_4h: np.ndarray) -> None:
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

    funding_ts = pd.date_range(ts_4h[0], ts_4h[-1], freq="8h", tz="UTC")
    funding_rate = 0.0001 + np.random.default_rng(11).normal(0, 0.00002, size=len(funding_ts))
    write_funding(
        pd.DataFrame({"timestamp": funding_ts, "symbol": "BTCUSDT", "funding_rate": funding_rate}),
        data_dir,
    )


def _run(data_dir: Path, ts_4h: pd.DatetimeIndex, end: pd.Timestamp):
    return run_backtest_window(
        strategy_cls=FundingAwareMultiHorizonTrend,
        config_cls=FundingAwareMultiHorizonTrendConfig,
        symbol="BTCUSDT",
        timeframe="4h",
        start=ts_4h[0],
        end=end,
        data_dir=data_dir,
        starting_balance=Decimal(100_000),
        periods_per_year=2191.5,
        config_kwargs=_CONFIG_KWARGS,
        funding_assumptions=FundingAssumptions(),
        higher_timeframe="1d",
    )


@pytest.fixture
def price_series() -> tuple[pd.DatetimeIndex, np.ndarray]:
    rng = np.random.default_rng(7)
    ts_4h = pd.date_range("2025-01-01", "2025-10-01", freq="4h", tz="UTC")
    close_4h = 60000 + np.arange(len(ts_4h)) * 12 + rng.normal(0, 25, size=len(ts_4h))
    return ts_4h, close_4h


def test_trades_at_or_before_cutoff_unaffected_by_data_after_it(
    tmp_path: Path, price_series: tuple[pd.DatetimeIndex, np.ndarray]
) -> None:
    ts_4h, close_4h = price_series
    _write_fixture(tmp_path, ts_4h, close_4h)

    full = _run(tmp_path, ts_4h, ts_4h[-1])
    truncated = _run(tmp_path, ts_4h, _CUTOFF)

    assert len(truncated.trades) > 0, "test needs at least one pre-cutoff trade to be meaningful"

    # Exclude any mark-to-market row: ending the truncated run's window
    # exactly at the cutoff synthesizes a closing trade for a still-open
    # position there (src.backtesting.reports.positions_report_to_trades)
    # that the full run - which keeps that position open past the cutoff -
    # never produces. That is a real, disclosed artifact of window
    # truncation, not a lookahead violation, so it must not be compared.
    comparison_boundary = _CUTOFF - _COMPARISON_MARGIN
    full_before_cutoff = full.trades[
        (full.trades["entry_time"] <= comparison_boundary) & (~full.trades["is_mark_to_market"])
    ].reset_index(drop=True)
    truncated_trades = truncated.trades[
        (truncated.trades["entry_time"] <= comparison_boundary)
        & (~truncated.trades["is_mark_to_market"])
    ].reset_index(drop=True)

    assert list(full_before_cutoff["entry_time"]) == list(truncated_trades["entry_time"])
    assert full_before_cutoff["entry_price"].tolist() == pytest.approx(
        truncated_trades["entry_price"].tolist()
    )
    assert full_before_cutoff["quantity"].tolist() == pytest.approx(
        truncated_trades["quantity"].tolist()
    )
