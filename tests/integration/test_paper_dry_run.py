"""End-to-end dry run: real backtest trades -> OrderIntents -> simulated
execution -> FillTracker summary. Proves the section 32 comparison pipeline
works against real strategy output, fully offline.
"""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path

import numpy as np
import pytest

from src.backtesting.costs import ExecutionAssumptions
from src.backtesting.runner import run_backtest_window
from src.execution.backtest_bridge import trades_to_intents
from src.execution.fill_tracking import FillTracker
from src.execution.simulated_adapter import SimulatedAdapterConfig, SimulatedExecutionAdapter
from src.strategies.trend_following import TrendFollowing, TrendFollowingConfig
from tests.integration.helpers import write_synthetic_klines


def test_dry_run_pipeline_end_to_end(tmp_path: Path) -> None:
    close = 100 + np.cumsum(np.random.default_rng(70).normal(0.02, 0.5, size=500))
    ts = write_synthetic_klines(tmp_path, close)

    window = run_backtest_window(
        strategy_cls=TrendFollowing,
        config_cls=TrendFollowingConfig,
        symbol="BTCUSDT",
        timeframe="1h",
        start=ts[0],
        end=ts[-1],
        data_dir=tmp_path,
        starting_balance=Decimal(100_000),
        periods_per_year=365.25 * 24,
    )
    assert not window.trades.empty

    intents = trades_to_intents(window.trades, symbol="BTCUSDT")
    assert len(intents) == len(window.trades)

    adapter = SimulatedExecutionAdapter(
        SimulatedAdapterConfig(slippage_bps=5.0, latency_seconds=0.1, seed=1)
    )
    tracker = FillTracker()
    for intent in intents:
        fill = adapter.submit(intent)
        tracker.record(intent, fill)

    summary = tracker.summary()
    assert summary.n_intents == len(intents)
    assert summary.n_rejected == 0
    assert summary.mean_latency_seconds == pytest.approx(0.1)
    assert summary.mean_slippage is not None
    assert summary.mean_slippage > 0  # adverse-positive convention, slippage_bps=5 always adverse


def test_adverse_fee_multiplier_changes_actual_backtest_costs(tmp_path: Path) -> None:
    close = 100 + np.cumsum(np.random.default_rng(71).normal(0.03, 0.4, size=500))
    ts = write_synthetic_klines(tmp_path, close)
    common = dict(
        strategy_cls=TrendFollowing,
        config_cls=TrendFollowingConfig,
        symbol="BTCUSDT",
        timeframe="1h",
        start=ts[0],
        end=ts[-1],
        data_dir=tmp_path,
        starting_balance=Decimal(100_000),
        periods_per_year=365.25 * 24,
    )
    base = run_backtest_window(
        **common,
        execution=ExecutionAssumptions(
            fee_multiplier=1.0, prob_slippage=0.0, spread_bps=0.0
        ),
    )
    adverse = run_backtest_window(
        **common,
        execution=ExecutionAssumptions(
            fee_multiplier=2.0, prob_slippage=0.0, spread_bps=0.0
        ),
    )

    assert not base.trades.empty
    # Later position sizes differ slightly because higher earlier fees reduce
    # equity, but the charged total must track the 2x scenario closely.
    assert adverse.trades["fees"].sum() == pytest.approx(
        2.0 * base.trades["fees"].sum(), rel=0.01
    )
    assert adverse.metrics.trade_metrics.net_return < base.metrics.trade_metrics.net_return
