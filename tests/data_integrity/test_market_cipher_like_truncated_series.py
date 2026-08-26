"""Truncated-series (no-lookahead) proof for
src.strategies.market_cipher_like.MarketCipherLike, required explicitly by
docs/PREREGISTRATION_market_cipher_like.md's "Przyczynowość" section: every
trade decided at or before some cutoff T must be IDENTICAL whether or not
any klines after T exist.

Same structural proof as
tests/data_integrity/test_funding_aware_multi_horizon_trend_truncated_series.py:
two full backtest runs on the same price fixture that differ only in how
much data after the cutoff exists on disk before the engine (and the
strategy's own `read_klines` call in `__init__`) ever sees it.
"""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from src.backtesting.runner import run_backtest_window
from src.data.schema import COLUMNS
from src.data.storage import write_klines
from src.strategies.market_cipher_like import MarketCipherLike, MarketCipherLikeConfig

_CONFIG_KWARGS = {"channel_span": 9, "momentum_span": 13, "signal_window": 4, "timeframe": "4h"}
_CUTOFF = pd.Timestamp("2025-06-01", tz="UTC")
# Same reasoning as the funding-aware truncated-series test: a decision
# within one bar of the boundary can legitimately differ between runs for
# a data-loading window-edge reason unrelated to lookahead.
_COMPARISON_MARGIN = pd.Timedelta(hours=8)


def _write_fixture(
    data_dir: Path, ts: pd.DatetimeIndex, close: np.ndarray, volume: np.ndarray
) -> None:
    df = pd.DataFrame(
        {
            "timestamp": ts,
            "open": close,
            "high": close + np.abs(close) * 0.002,
            "low": close - np.abs(close) * 0.002,
            "close": close,
            "volume": volume,
            "turnover": 10_000.0,
            "symbol": "BTCUSDT",
            "timeframe": "4h",
        }
    )[list(COLUMNS)]
    write_klines(df, data_dir)


def _run(data_dir: Path, ts: pd.DatetimeIndex, end: pd.Timestamp):
    return run_backtest_window(
        strategy_cls=MarketCipherLike,
        config_cls=MarketCipherLikeConfig,
        symbol="BTCUSDT",
        timeframe="4h",
        start=ts[0],
        end=end,
        data_dir=data_dir,
        starting_balance=Decimal(100_000),
        periods_per_year=2191.5,
        config_kwargs={**_CONFIG_KWARGS, "data_dir": str(data_dir)},
    )


@pytest.fixture
def price_series() -> tuple[pd.DatetimeIndex, np.ndarray, np.ndarray]:
    # A pure smooth sinusoid (tried first) produced momentum-histogram
    # crossovers whose money-flow reading at that exact bar structurally
    # never agreed in sign (money_flow lags a leading-indicator turning
    # point by construction) - zero confirmed entries regardless of random
    # seed, not a lookahead bug, just an unrepresentative fixture. A
    # regime-switching random walk (occasional drift changes, real-
    # microstructure-scale noise) is closer to actual return behavior and
    # produces plenty of genuine confirmed crossovers on both sides of the
    # cutoff.
    rng = np.random.default_rng(0)
    ts = pd.date_range("2025-01-01", "2025-10-01", freq="4h", tz="UTC")
    n = len(ts)
    regime_len = 60
    drift = np.repeat(rng.normal(0, 8, size=n // regime_len + 1), regime_len)[:n]
    returns = drift + rng.normal(0, 60, size=n)
    close = 60000 + np.cumsum(returns)
    volume = 100 + np.abs(returns) * 2 + rng.normal(0, 10, size=n).clip(min=0)
    return ts, close, volume


def test_trades_at_or_before_cutoff_unaffected_by_data_after_it(
    tmp_path: Path, price_series: tuple[pd.DatetimeIndex, np.ndarray, np.ndarray]
) -> None:
    ts, close, volume = price_series
    _write_fixture(tmp_path, ts, close, volume)

    full = _run(tmp_path, ts, ts[-1])
    truncated = _run(tmp_path, ts, _CUTOFF)

    assert len(truncated.trades) > 0, "test needs at least one pre-cutoff trade to be meaningful"

    # Exclude any mark-to-market row, same reasoning as the funding-aware
    # truncated-series test: ending the truncated run exactly at the
    # cutoff synthesizes a closing trade for a still-open position that
    # the full run (which keeps it open past the cutoff) never produces.
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


def test_run_is_deterministic(
    tmp_path: Path, price_series: tuple[pd.DatetimeIndex, np.ndarray, np.ndarray]
) -> None:
    ts, close, volume = price_series
    _write_fixture(tmp_path, ts, close, volume)

    first = _run(tmp_path, ts, ts[-1])
    second = _run(tmp_path, ts, ts[-1])

    assert list(first.trades["entry_time"]) == list(second.trades["entry_time"])
    assert first.trades["entry_price"].tolist() == pytest.approx(
        second.trades["entry_price"].tolist()
    )
