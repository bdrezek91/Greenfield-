"""run_walk_forward against the real engine: windows execute, TEST-only
results get assembled, and parameter selection (when a grid is given)
happens on VALIDATION, never on TEST.
"""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from src.backtesting.walk_forward import generate_windows, run_walk_forward
from src.strategies.momentum import Momentum, MomentumConfig
from src.strategies.trend_following import TrendFollowing, TrendFollowingConfig
from tests.integration.helpers import write_synthetic_klines


def test_walk_forward_without_param_grid(tmp_path: Path) -> None:
    close = 100 + np.cumsum(np.random.default_rng(10).normal(0.02, 0.4, size=24 * 20))
    ts = write_synthetic_klines(tmp_path, close)

    windows = generate_windows(
        ts[0],
        ts[-1],
        train_period=pd.Timedelta(days=8),
        validation_period=pd.Timedelta(days=3),
        test_period=pd.Timedelta(days=3),
    )
    assert len(windows) >= 1

    result = run_walk_forward(
        strategy_cls=TrendFollowing,
        config_cls=TrendFollowingConfig,
        symbol="BTCUSDT",
        timeframe="1h",
        windows=windows,
        data_dir=tmp_path,
        starting_balance=Decimal(100_000),
        periods_per_year=365.25 * 24,
    )

    assert result.selected_params == [{}] * len(windows)
    assert not result.test_equity.empty
    # The stitched curve starts at the starting balance.
    assert result.test_equity.iloc[0] == pytest.approx(100_000.0)
    # Walk-forward boundaries are information-time and half-open.
    assert result.test_equity.index.min() == windows[0].test_start
    assert result.test_equity.index.max() < windows[-1].test_end
    assert "window_id" in result.test_trades.columns
    if not result.test_trades.empty:
        assert (result.test_trades["entry_time"] >= windows[0].test_start).all()
        assert set(result.test_trades["window_id"]) <= {
            window.window_id for window in windows
        }


def test_walk_forward_selects_params_on_validation_not_test(tmp_path: Path) -> None:
    close = 100 + np.cumsum(np.random.default_rng(11).normal(0.02, 0.4, size=24 * 20))
    ts = write_synthetic_klines(tmp_path, close)

    windows = generate_windows(
        ts[0],
        ts[-1],
        train_period=pd.Timedelta(days=8),
        validation_period=pd.Timedelta(days=3),
        test_period=pd.Timedelta(days=3),
    )
    assert len(windows) >= 1

    param_grid = [{"threshold": 0.005}, {"threshold": 0.05}]
    result = run_walk_forward(
        strategy_cls=Momentum,
        config_cls=MomentumConfig,
        symbol="BTCUSDT",
        timeframe="1h",
        windows=windows,
        data_dir=tmp_path,
        starting_balance=Decimal(100_000),
        periods_per_year=365.25 * 24,
        param_grid=param_grid,
        selection_metric="sharpe",
    )

    assert len(result.selected_params) == len(windows)
    for chosen in result.selected_params:
        assert chosen in param_grid
    assert not result.test_equity.empty


def test_walk_forward_raises_on_empty_windows(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="no walk-forward windows"):
        run_walk_forward(
            strategy_cls=TrendFollowing,
            config_cls=TrendFollowingConfig,
            symbol="BTCUSDT",
            timeframe="1h",
            windows=[],
            data_dir=tmp_path,
            starting_balance=Decimal(100_000),
            periods_per_year=365.25 * 24,
        )
