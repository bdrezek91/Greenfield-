"""ATR-based exit (src.strategies.base.BenchmarkStrategyConfig.use_atr_exit):
a stop/target derived from recent volatility should close a position much
sooner than the fixed `holding_period_bars` count when price moves sharply
right after entry, and `holding_period_bars` must still apply as a safety
cap when neither stop nor target is ever touched.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
import pytest
from nautilus_trader.model.data import BarSpecification, BarType
from nautilus_trader.model.enums import AggregationSource, BarAggregation, PriceType
from nautilus_trader.model.identifiers import InstrumentId

from src.backtesting.data_adapter import bar_type_for
from src.backtesting.engine import BacktestRunSpec, build_engine
from src.data.schema import COLUMNS
from src.data.storage import write_klines
from src.strategies.momentum import Momentum, MomentumConfig

_INSTRUMENT_ID = InstrumentId.from_str("BTCUSDT-PERP.BYBIT")
_BAR_TYPE = BarType(
    _INSTRUMENT_ID,
    BarSpecification(1, BarAggregation.HOUR, PriceType.LAST),
    AggregationSource.EXTERNAL,
)
_CONFIG_KWARGS = {
    "lookback_bars": 1,
    "threshold": 0.02,
}  # deque size 2: fires exactly on the jump bar


def _bars_df(close: np.ndarray, spike_idx: int | None = None) -> pd.DataFrame:
    high, low = close + 0.05, close - 0.05
    if spike_idx is not None:
        high[spike_idx] = close[spike_idx] + 50.0  # far past any sane ATR(quiet)*2 target
    ts = pd.date_range("2024-01-01", periods=len(close), freq="1h", tz="UTC")
    return pd.DataFrame(
        {
            "timestamp": ts,
            "open": close,
            "high": high,
            "low": low,
            "close": close,
            "volume": 10.0,
            "turnover": 1000.0,
            "symbol": "BTCUSDT",
            "timeframe": "1h",
        }
    )[list(COLUMNS)]


def _quiet_then_jump(n_quiet: int, n_tail: int, seed: int) -> np.ndarray:
    """Flat, tightly-ranged warmup (a small, stable ATR) -> one single-bar
    jump that fires Momentum's BUY signal (deque size 2, so it only ever
    compares two consecutive closes) -> a flat tail."""
    rng = np.random.default_rng(seed)
    quiet = 100 + rng.normal(0, 0.02, size=n_quiet)
    jump = np.array([103.0])  # +3% vs ~100, well past the 0.02 threshold
    tail = 103.0 + rng.normal(0, 0.02, size=n_tail)
    return np.concatenate([quiet, jump, tail])


def _run(tmp_path: Path, df: pd.DataFrame, **config_kwargs) -> pd.DataFrame:
    write_klines(df, tmp_path)
    spec = BacktestRunSpec(
        symbols=["BTCUSDT"],
        timeframe="1h",
        start=df["timestamp"].iloc[0],
        end=df["timestamp"].iloc[-1],
        data_dir=tmp_path,
    )
    engine, instruments = build_engine(spec)
    instrument = instruments["BTCUSDT"]
    bar_type = bar_type_for(instrument, "1h")
    config = MomentumConfig(instrument_id=instrument.id, bar_type=bar_type, **config_kwargs)
    engine.add_strategy(Momentum(config))
    engine.run()
    positions = engine.trader.generate_positions_report()
    engine.dispose()
    return positions


def _bars_held(positions: pd.DataFrame) -> float:
    closed = positions[positions["ts_closed"].notna()]
    assert not closed.empty
    opened = pd.to_datetime(closed["ts_opened"], utc=True)
    exited = pd.to_datetime(closed["ts_closed"], utc=True)
    return float(((exited - opened).dt.total_seconds() / 3600).iloc[0])


def test_atr_exit_closes_far_sooner_than_the_fixed_holding_period(tmp_path: Path) -> None:
    n_quiet = 20
    close = _quiet_then_jump(n_quiet=n_quiet, n_tail=100, seed=1)
    spike_idx = n_quiet + 1  # the bar right after the entry (jump) bar
    df = _bars_df(close, spike_idx=spike_idx)

    positions = _run(
        tmp_path,
        df,
        **_CONFIG_KWARGS,
        holding_period_bars=200,
        use_atr_exit=True,
        atr_period=10,
        atr_exit_multiple=2.0,
    )

    # The spike bar lands one bar after entry - the target must be hit by
    # then, nowhere near the 200-bar holding_period_bars cap.
    assert _bars_held(positions) <= 2


def test_holding_period_still_caps_an_atr_exit_that_never_triggers(tmp_path: Path) -> None:
    """No spike this time - price stays inside any sane ATR band after
    entry, so the fixed holding_period_bars cap must still be the thing
    that closes the trade (an ATR exit is additive, never a replacement
    for the safety cap)."""
    close = _quiet_then_jump(n_quiet=20, n_tail=60, seed=2)
    df = _bars_df(close, spike_idx=None)

    positions = _run(
        tmp_path,
        df,
        **_CONFIG_KWARGS,
        holding_period_bars=10,
        use_atr_exit=True,
        atr_period=10,
        atr_exit_multiple=2.0,
    )

    assert _bars_held(positions) == 10


def test_atr_exit_config_rejects_too_short_period() -> None:
    with pytest.raises(ValueError, match="atr_period"):
        MomentumConfig(
            instrument_id=_INSTRUMENT_ID, bar_type=_BAR_TYPE, use_atr_exit=True, atr_period=1
        )


def test_atr_exit_config_rejects_non_positive_multiple() -> None:
    with pytest.raises(ValueError, match="atr_exit_multiple"):
        MomentumConfig(
            instrument_id=_INSTRUMENT_ID,
            bar_type=_BAR_TYPE,
            use_atr_exit=True,
            atr_exit_multiple=0.0,
        )
