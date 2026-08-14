"""Metrics must match hand-computed values on small, known fixtures."""

from __future__ import annotations

import math

import pandas as pd
import pytest

from src.analytics.metrics import (
    compute_equity_metrics,
    compute_trade_metrics,
    exposure_fraction,
    longest_losing_streak,
    trade_pnl,
)


def _trades() -> pd.DataFrame:
    # Trade 1: long, win. Trade 2: short, win. Trade 3: long, loss. Trade 4: long, loss.
    return pd.DataFrame(
        {
            "entry_time": pd.to_datetime(
                ["2024-01-01T00:00", "2024-01-02T00:00", "2024-01-03T00:00", "2024-01-04T00:00"],
                utc=True,
            ),
            "exit_time": pd.to_datetime(
                ["2024-01-01T04:00", "2024-01-02T04:00", "2024-01-03T04:00", "2024-01-04T04:00"],
                utc=True,
            ),
            "quantity": [1.0, -1.0, 1.0, 1.0],
            "entry_price": [100.0, 100.0, 100.0, 100.0],
            "exit_price": [110.0, 90.0, 95.0, 98.0],
            "fees": [1.0, 1.0, 1.0, 1.0],
            "funding_cost": [0.0, 0.0, 0.0, 0.0],
        }
    )


def test_trade_pnl_long_and_short_signs() -> None:
    df = trade_pnl(_trades())
    assert df["gross_pnl"].tolist() == [10.0, 10.0, -5.0, -2.0]
    assert df["net_pnl"].tolist() == [9.0, 9.0, -6.0, -3.0]


def test_compute_trade_metrics_known_values() -> None:
    metrics = compute_trade_metrics(_trades())
    assert metrics.trades == 4
    assert metrics.net_return == pytest.approx(9.0)
    assert metrics.win_rate == pytest.approx(0.5)
    assert metrics.avg_win == pytest.approx(9.0)
    assert metrics.avg_loss == pytest.approx(-4.5)
    assert metrics.profit_factor == pytest.approx(18.0 / 9.0)
    assert metrics.fees == pytest.approx(4.0)
    assert metrics.turnover == pytest.approx(400.0)
    assert metrics.avg_r is None  # no r_multiple column supplied


def test_compute_trade_metrics_empty() -> None:
    metrics = compute_trade_metrics(pd.DataFrame())
    assert metrics.trades == 0
    assert metrics.net_return == 0.0


def test_longest_losing_streak() -> None:
    pnl = pd.Series([1, -1, -1, -1, 2, -1, -1])
    assert longest_losing_streak(pnl) == 3


def test_r_multiple_column_used_when_present() -> None:
    trades = _trades()
    trades["r_multiple"] = [1.5, 1.0, -1.0, -0.5]
    metrics = compute_trade_metrics(trades)
    assert metrics.avg_r == pytest.approx(0.25)
    assert metrics.median_r == pytest.approx(0.25)


def test_exposure_fraction_full_coverage() -> None:
    trades = pd.DataFrame(
        {
            "entry_time": pd.to_datetime(["2024-01-01T00:00"], utc=True),
            "exit_time": pd.to_datetime(["2024-01-02T00:00"], utc=True),
        }
    )
    start = pd.Timestamp("2024-01-01T00:00", tz="UTC")
    end = pd.Timestamp("2024-01-02T00:00", tz="UTC")
    assert exposure_fraction(trades, start, end) == pytest.approx(1.0)


def test_exposure_fraction_half_coverage_no_overlap() -> None:
    trades = pd.DataFrame(
        {
            "entry_time": pd.to_datetime(["2024-01-01T00:00"], utc=True),
            "exit_time": pd.to_datetime(["2024-01-01T12:00"], utc=True),
        }
    )
    start = pd.Timestamp("2024-01-01T00:00", tz="UTC")
    end = pd.Timestamp("2024-01-02T00:00", tz="UTC")
    assert exposure_fraction(trades, start, end) == pytest.approx(0.5)


def test_exposure_fraction_merges_overlapping_intervals() -> None:
    trades = pd.DataFrame(
        {
            "entry_time": pd.to_datetime(["2024-01-01T00:00", "2024-01-01T06:00"], utc=True),
            "exit_time": pd.to_datetime(["2024-01-01T12:00", "2024-01-01T18:00"], utc=True),
        }
    )
    start = pd.Timestamp("2024-01-01T00:00", tz="UTC")
    end = pd.Timestamp("2024-01-02T00:00", tz="UTC")
    # Union of [00:00,12:00] and [06:00,18:00] = [00:00,18:00] = 18h out of 24h.
    assert exposure_fraction(trades, start, end) == pytest.approx(18 / 24)


def test_exposure_fraction_empty_trades_is_zero() -> None:
    start = pd.Timestamp("2024-01-01T00:00", tz="UTC")
    end = pd.Timestamp("2024-01-02T00:00", tz="UTC")
    assert exposure_fraction(pd.DataFrame(), start, end) == 0.0


def test_equity_metrics_growing_equity_positive_sharpe() -> None:
    idx = pd.date_range("2024-01-01", periods=100, freq="D", tz="UTC")
    equity = pd.Series([10_000 * (1.001**i) for i in range(100)], index=idx)
    metrics = compute_equity_metrics(equity, periods_per_year=365.25)
    assert metrics.cagr > 0
    assert metrics.sharpe > 0
    assert metrics.max_drawdown == pytest.approx(0.0, abs=1e-9)


def test_equity_metrics_flat_equity_is_nan_sharpe() -> None:
    idx = pd.date_range("2024-01-01", periods=10, freq="D", tz="UTC")
    equity = pd.Series([10_000] * 10, index=idx)
    metrics = compute_equity_metrics(equity, periods_per_year=365.25)
    assert math.isnan(metrics.sharpe)
    assert metrics.max_drawdown == pytest.approx(0.0)


def test_equity_metrics_detects_drawdown() -> None:
    idx = pd.date_range("2024-01-01", periods=5, freq="D", tz="UTC")
    equity = pd.Series([100, 120, 90, 95, 110], index=idx, dtype=float)
    metrics = compute_equity_metrics(equity, periods_per_year=365.25)
    assert metrics.max_drawdown == pytest.approx((90 - 120) / 120)


def test_sortino_downside_deviation_uses_all_periods_not_just_losses() -> None:
    # Known returns: 0.02, -0.01, 0.03, -0.02, 0.01 (5 periods, 2 losses).
    returns = [0.02, -0.01, 0.03, -0.02, 0.01]
    equity_values = [100.0]
    for r in returns:
        equity_values.append(equity_values[-1] * (1 + r))
    idx = pd.date_range("2024-01-01", periods=len(equity_values), freq="D", tz="UTC")
    equity = pd.Series(equity_values, index=idx)

    metrics = compute_equity_metrics(equity, periods_per_year=1)

    # downside_sq_sum = 0.01^2 + 0.02^2 = 0.0005; divided by ALL 5 periods
    # (not just the 2 losing ones) -> downside_std = sqrt(0.0001) = 0.01.
    # mean(returns) = 0.006 -> sortino = 0.006 / 0.01 = 0.6.
    assert metrics.sortino == pytest.approx(0.6, abs=1e-6)


def test_equity_metrics_too_short_is_nan() -> None:
    idx = pd.date_range("2024-01-01", periods=1, freq="D", tz="UTC")
    equity = pd.Series([100.0], index=idx)
    metrics = compute_equity_metrics(equity, periods_per_year=365.25)
    assert math.isnan(metrics.cagr)
    assert math.isnan(metrics.sharpe)
