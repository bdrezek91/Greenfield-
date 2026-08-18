from __future__ import annotations

from decimal import Decimal
from pathlib import Path

import numpy as np
import pandas as pd

from src.backtesting.funding import FundingAssumptions
from src.backtesting.runner import run_backtest_window
from src.data.storage import write_funding
from src.strategies.cross_sectional_momentum import (
    CrossSectionalMomentum,
    CrossSectionalMomentumConfig,
)
from src.strategies.funding_carry import FundingCarry, FundingCarryConfig
from tests.integration.helpers import write_synthetic_klines


def test_cross_sectional_runner_loads_all_peers_in_one_engine(tmp_path: Path) -> None:
    n = 180
    ts = write_synthetic_klines(tmp_path, np.linspace(100, 160, n), "BTCUSDT")
    write_synthetic_klines(tmp_path, np.linspace(100, 120, n), "ETHUSDT")
    write_synthetic_klines(tmp_path, np.linspace(100, 80, n), "SOLUSDT")

    result = run_backtest_window(
        strategy_cls=CrossSectionalMomentum,
        config_cls=CrossSectionalMomentumConfig,
        symbol="BTCUSDT",
        timeframe="1h",
        start=ts[1],
        end=ts[-1],
        data_dir=tmp_path,
        starting_balance=Decimal(100_000),
        periods_per_year=8766,
        config_kwargs={"lookback_bars": 20, "holding_period_bars": 6},
        reference_symbols=("ETHUSDT", "SOLUSDT"),
        warmup_start=ts[1] - pd.Timedelta(hours=25),
    )

    assert len(result.config.peer_instrument_ids) == 2
    assert result.metrics.trade_metrics.trades > 0


def test_funding_carry_reads_historical_rates_and_trades(tmp_path: Path) -> None:
    n = 180
    ts = write_synthetic_klines(tmp_path, np.linspace(100, 105, n), "BTCUSDT")
    funding = pd.DataFrame(
        {
            "timestamp": pd.date_range(ts[0], periods=24, freq="8h"),
            "symbol": "BTCUSDT",
            "funding_rate": 0.001,
        }
    )
    write_funding(funding, tmp_path)
    assumptions = FundingAssumptions.from_history(funding)

    result = run_backtest_window(
        strategy_cls=FundingCarry,
        config_cls=FundingCarryConfig,
        symbol="BTCUSDT",
        timeframe="1h",
        start=ts[1],
        end=ts[-1],
        data_dir=tmp_path,
        starting_balance=Decimal(100_000),
        periods_per_year=8766,
        config_kwargs={
            "persistence_observations": 2,
            "min_abs_funding_rate": 0.0001,
            "holding_period_bars": 6,
        },
        funding_assumptions=assumptions,
    )

    assert result.metrics.trade_metrics.trades > 0
    assert result.funding_applied is True
