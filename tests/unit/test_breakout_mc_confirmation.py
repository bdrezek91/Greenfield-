"""BreakoutMcConfirmationConfig has no safe default for data_dir/timeframe
(same pattern as MarketCipherLikeConfig) - validated loudly, never silently
defaulted. Signal logic: filter requires active histogram agreement, veto
blocks only on active disagreement - see the module docstring for why
these are genuinely different, not two names for the same rule.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
import pytest
from nautilus_trader.model.data import Bar, BarSpecification, BarType
from nautilus_trader.model.enums import AggregationSource, BarAggregation, OrderSide, PriceType
from nautilus_trader.model.identifiers import InstrumentId
from nautilus_trader.model.objects import Price, Quantity

from src.data.schema import COLUMNS
from src.data.storage import write_klines
from src.strategies.breakout_mc_confirmation import (
    BreakoutMcConfirmation,
    BreakoutMcConfirmationConfig,
)

_INSTRUMENT_ID = InstrumentId.from_str("BTCUSDT-PERP.BYBIT")
_BAR_TYPE_4H = BarType(
    _INSTRUMENT_ID,
    BarSpecification(4, BarAggregation.HOUR, PriceType.LAST),
    AggregationSource.EXTERNAL,
)


def test_missing_data_dir_raises() -> None:
    with pytest.raises(ValueError, match="data_dir"):
        BreakoutMcConfirmationConfig(
            instrument_id=_INSTRUMENT_ID, bar_type=_BAR_TYPE_4H, timeframe="4h"
        )


def test_missing_timeframe_raises() -> None:
    with pytest.raises(ValueError, match="timeframe"):
        BreakoutMcConfirmationConfig(
            instrument_id=_INSTRUMENT_ID, bar_type=_BAR_TYPE_4H, data_dir="/tmp"
        )


def test_invalid_mode_raises() -> None:
    with pytest.raises(ValueError, match="mode"):
        BreakoutMcConfirmationConfig(
            instrument_id=_INSTRUMENT_ID,
            bar_type=_BAR_TYPE_4H,
            data_dir="/tmp",
            timeframe="4h",
            mode="something_else",
        )


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("lookback_bars", 1),
        ("channel_span", 1),
        ("momentum_span", 1),
        ("signal_window", 1),
        ("money_flow_window", 1),
    ],
)
def test_invalid_numeric_params_raise(field: str, value: int) -> None:
    with pytest.raises(ValueError):
        BreakoutMcConfirmationConfig(
            instrument_id=_INSTRUMENT_ID,
            bar_type=_BAR_TYPE_4H,
            data_dir="/tmp",
            timeframe="4h",
            **{field: value},
        )


def test_missing_klines_on_disk_raises(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="no historical klines"):
        BreakoutMcConfirmation(
            BreakoutMcConfirmationConfig(
                instrument_id=_INSTRUMENT_ID,
                bar_type=_BAR_TYPE_4H,
                data_dir=str(tmp_path),
                timeframe="4h",
            )
        )


def _write_sufficient_klines(data_dir: Path, *, n: int = 200, seed: int = 7) -> None:
    ts = pd.date_range("2025-01-01", periods=n, freq="4h", tz="UTC")
    rng = np.random.default_rng(seed)
    close = 100.0 + np.cumsum(rng.normal(0, 1, n))
    df = pd.DataFrame(
        {
            "timestamp": ts,
            "open": close,
            "high": close + 1,
            "low": close - 1,
            "close": close,
            "volume": 10.0,
            "turnover": 1000.0,
            "symbol": "BTCUSDT",
            "timeframe": "4h",
        }
    )[list(COLUMNS)]
    write_klines(df, data_dir)


def _bar(ts_event: int, *, high: float, low: float, close: float) -> Bar:
    return Bar(
        bar_type=_BAR_TYPE_4H,
        open=Price.from_str(f"{close:.2f}"),
        high=Price.from_str(f"{high:.2f}"),
        low=Price.from_str(f"{low:.2f}"),
        close=Price.from_str(f"{close:.2f}"),
        volume=Quantity.from_str("1.0"),
        ts_event=ts_event,
        ts_init=ts_event,
    )


def test_insufficient_klines_for_warmup_raises(tmp_path: Path) -> None:
    _write_sufficient_klines(tmp_path, n=5)
    with pytest.raises(ValueError, match="insufficient klines history"):
        BreakoutMcConfirmation(
            BreakoutMcConfirmationConfig(
                instrument_id=_INSTRUMENT_ID,
                bar_type=_BAR_TYPE_4H,
                data_dir=str(tmp_path),
                timeframe="4h",
            )
        )


def _strategy(tmp_path: Path, mode: str) -> BreakoutMcConfirmation:
    _write_sufficient_klines(tmp_path)
    return BreakoutMcConfirmation(
        BreakoutMcConfirmationConfig(
            instrument_id=_INSTRUMENT_ID,
            bar_type=_BAR_TYPE_4H,
            data_dir=str(tmp_path),
            timeframe="4h",
            lookback_bars=3,
            mode=mode,
        )
    )


def test_no_breakout_produces_no_signal_regardless_of_mode(tmp_path: Path) -> None:
    strat = _strategy(tmp_path, "filter")
    for i in range(3):
        assert strat.signal(_bar(i, high=105.0, low=95.0, close=100.0)) is None
    # Fourth bar stays inside the prior 3-bar range - no breakout either way.
    assert strat.signal(_bar(3, high=104.0, low=96.0, close=101.0)) is None


def test_filter_blocks_breakout_when_histogram_unavailable(tmp_path: Path) -> None:
    strat = _strategy(tmp_path, "filter")
    for i in range(3):
        strat.signal(_bar(i, high=105.0, low=95.0, close=100.0))
    # These small ts_event values are far before the loaded klines' own
    # (2025+) timestamps, so AsOfSeries.window_ending_at's as-of lookup
    # finds nothing yet - "filter" must stay flat with no confirmation.
    result = strat.signal(_bar(3, high=110.0, low=100.0, close=106.0))
    assert result is None


def test_veto_allows_breakout_when_histogram_unavailable(tmp_path: Path) -> None:
    strat = _strategy(tmp_path, "veto")
    for i in range(3):
        strat.signal(_bar(i, high=105.0, low=95.0, close=100.0))
    # Same "no histogram reading available" situation as the filter test
    # above - veto has nothing to veto with, so the breakout proceeds.
    result = strat.signal(_bar(3, high=110.0, low=100.0, close=106.0))
    assert result == OrderSide.BUY
