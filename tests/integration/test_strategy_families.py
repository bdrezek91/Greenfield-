"""Phase 6 strategy families must fire on the specific conditions they're
designed for, and stay flat otherwise - each tested against a synthetic
price series engineered to isolate that condition.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

from src.backtesting.data_adapter import bar_type_for
from src.backtesting.engine import BacktestRunSpec, build_engine
from src.data.schema import COLUMNS
from src.data.storage import write_klines
from src.strategies.breakout import Breakout, BreakoutConfig
from src.strategies.momentum import Momentum, MomentumConfig
from src.strategies.volatility_expansion import VolatilityExpansion, VolatilityExpansionConfig
from tests.integration.helpers import run_strategy


def test_momentum_stays_flat_below_threshold(tmp_path: Path) -> None:
    # Tiny drift (well under the default 1% / 10-bar threshold).
    close = 100 + np.arange(100, dtype=float) * 0.001
    positions, _ = run_strategy(tmp_path, close, Momentum, MomentumConfig)
    assert len(positions) == 0


def test_momentum_enters_long_above_threshold(tmp_path: Path) -> None:
    close = 100 + np.arange(200, dtype=float) * 0.5  # well past the 1% threshold
    positions, _ = run_strategy(tmp_path, close, Momentum, MomentumConfig)
    assert len(positions) > 0
    assert (positions["entry"] == "BUY").all()


def test_momentum_enters_short_below_negative_threshold(tmp_path: Path) -> None:
    # Same relative magnitude as the long case above (~1.7%+ per 10-bar window).
    close = 300 - np.arange(200, dtype=float) * 0.5
    positions, _ = run_strategy(tmp_path, close, Momentum, MomentumConfig)
    assert len(positions) > 0
    assert (positions["entry"] == "SELL").all()


def test_breakout_stays_flat_inside_the_range(tmp_path: Path) -> None:
    rng = np.random.default_rng(0)
    close = 100 + rng.uniform(-0.2, 0.2, size=100)  # noise well inside any lookback range
    positions, _ = run_strategy(tmp_path, close, Breakout, BreakoutConfig)
    assert len(positions) == 0


def test_breakout_enters_long_on_new_high(tmp_path: Path) -> None:
    flat = np.full(25, 100.0)
    breakout = np.array([110.0] + [111.0] * 24)  # decisively above the prior 25-bar high
    close = np.concatenate([flat, breakout])
    positions, _ = run_strategy(tmp_path, close, Breakout, BreakoutConfig)
    assert len(positions) > 0
    assert positions["entry"].iloc[0] == "BUY"


def test_breakout_enters_short_on_new_low(tmp_path: Path) -> None:
    flat = np.full(25, 100.0)
    breakdown = np.array([90.0] + [89.0] * 24)  # decisively below the prior 25-bar low
    close = np.concatenate([flat, breakdown])
    positions, _ = run_strategy(tmp_path, close, Breakout, BreakoutConfig)
    assert len(positions) > 0
    assert positions["entry"].iloc[0] == "SELL"


def test_volatility_expansion_stays_flat_on_uniform_ranges(tmp_path: Path) -> None:
    # write_synthetic_klines gives every bar the same +/-0.5 range - never expands.
    close = 100 + np.cumsum(np.random.default_rng(1).normal(0, 0.1, size=100))
    positions, _ = run_strategy(tmp_path, close, VolatilityExpansion, VolatilityExpansionConfig)
    assert len(positions) == 0


def test_volatility_expansion_enters_on_range_spike(tmp_path: Path) -> None:
    ts_count = 30
    tmp = np.full(ts_count, 100.0)  # baseline: flat closes -> narrow, uniform ranges
    close = np.concatenate([tmp, [100.0]])
    positions, _ = _run_with_range_spike(tmp_path, close, direction=1.0)
    assert len(positions) > 0
    assert positions["entry"].iloc[0] == "BUY"


def test_volatility_expansion_direction_follows_the_spike_bar(tmp_path: Path) -> None:
    close = np.full(31, 100.0)
    positions, _ = _run_with_range_spike(tmp_path, close, direction=-1.0)
    assert len(positions) > 0
    assert positions["entry"].iloc[0] == "SELL"


def _run_with_range_spike(tmp_path: Path, close: np.ndarray, direction: float):
    """Like run_strategy, but widens the penultimate bar's range and open/close
    direction so it decisively exceeds the rolling average range baseline
    (write_synthetic_klines gives every bar the same narrow +/-0.5 range,
    which never triggers expansion on its own).
    """
    ts = pd.date_range("2024-01-01", periods=len(close), freq="1h", tz="UTC")
    df = pd.DataFrame(
        {
            "timestamp": ts,
            "open": close,
            "high": close + 0.5,
            "low": close - 0.5,
            "close": close,
            "volume": 10.0,
            "turnover": 1000.0,
            "symbol": "BTCUSDT",
            "timeframe": "1h",
        }
    )
    # The penultimate bar creates the signal; the final closed bar is the
    # earliest honest execution opportunity under entry_delay_bars=1.
    signal_idx = df.index[-2]
    df.loc[signal_idx, "high"] = close[-2] + 20.0 * max(direction, 0.0) + 1.0
    df.loc[signal_idx, "low"] = close[-2] - 20.0 * max(-direction, 0.0) - 1.0
    df.loc[signal_idx, "close"] = close[-2] + direction * 15.0
    df = df[list(COLUMNS)]
    write_klines(df, tmp_path)

    spec = BacktestRunSpec(
        symbols=["BTCUSDT"],
        timeframe="1h",
        start=ts[0] + pd.Timedelta(hours=1),
        end=ts[-1] + pd.Timedelta(hours=1, nanoseconds=1),
        data_dir=tmp_path,
    )
    engine, instruments = build_engine(spec)
    instrument = instruments["BTCUSDT"]
    bar_type = bar_type_for(instrument, "1h")
    config = VolatilityExpansionConfig(instrument_id=instrument.id, bar_type=bar_type)
    engine.add_strategy(VolatilityExpansion(config))
    engine.run()
    positions = engine.trader.generate_positions_report()
    account = engine.trader.generate_account_report(next(iter(engine.list_venues())))
    engine.dispose()
    return positions, account
