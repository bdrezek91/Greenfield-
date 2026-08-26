"""MarketCipherLikeConfig has no safe default for data_dir or timeframe
(same pattern as FundingContrarianConfig.data_dir and
FundingAwareMultiHorizonTrendConfig.higher_bar_type) - validated loudly in
__post_init__/__init__, never silently defaulted. See
docs/PREREGISTRATION_market_cipher_like.md for the frozen strategy this
config drives.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
import pytest
from nautilus_trader.model.data import BarSpecification, BarType
from nautilus_trader.model.enums import AggregationSource, BarAggregation, PriceType
from nautilus_trader.model.identifiers import InstrumentId

from src.data.schema import COLUMNS
from src.data.storage import write_klines
from src.strategies.market_cipher_like import MarketCipherLike, MarketCipherLikeConfig

_INSTRUMENT_ID = InstrumentId.from_str("BTCUSDT-PERP.BYBIT")
_BAR_TYPE_4H = BarType(
    _INSTRUMENT_ID,
    BarSpecification(4, BarAggregation.HOUR, PriceType.LAST),
    AggregationSource.EXTERNAL,
)


def test_missing_data_dir_raises() -> None:
    with pytest.raises(ValueError, match="data_dir"):
        MarketCipherLikeConfig(instrument_id=_INSTRUMENT_ID, bar_type=_BAR_TYPE_4H, timeframe="4h")


def test_missing_timeframe_raises() -> None:
    with pytest.raises(ValueError, match="timeframe"):
        MarketCipherLikeConfig(
            instrument_id=_INSTRUMENT_ID, bar_type=_BAR_TYPE_4H, data_dir="/tmp"
        )


def test_unsupported_timeframe_raises() -> None:
    with pytest.raises(ValueError, match="timeframe"):
        MarketCipherLikeConfig(
            instrument_id=_INSTRUMENT_ID, bar_type=_BAR_TYPE_4H, data_dir="/tmp", timeframe="3h"
        )


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("channel_span", 1),
        ("momentum_span", 1),
        ("signal_window", 1),
        ("money_flow_window", 1),
        ("rsi_window", 1),
        ("pivot_left", 0),
        ("pivot_right", 0),
    ],
)
def test_invalid_numeric_params_raise(field: str, value: int) -> None:
    with pytest.raises(ValueError):
        MarketCipherLikeConfig(
            instrument_id=_INSTRUMENT_ID,
            bar_type=_BAR_TYPE_4H,
            data_dir="/tmp",
            timeframe="4h",
            **{field: value},
        )


def test_missing_klines_on_disk_raises(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="no historical klines"):
        MarketCipherLike(
            MarketCipherLikeConfig(
                instrument_id=_INSTRUMENT_ID,
                bar_type=_BAR_TYPE_4H,
                data_dir=str(tmp_path),
                timeframe="4h",
            )
        )


def test_insufficient_klines_for_warmup_raises(tmp_path: Path) -> None:
    # A handful of bars can never satisfy momentum_span=21's EMA warmup -
    # momentum_money_flow_frame returns an empty frame, and construction
    # must fail closed rather than silently start with no features.
    ts = pd.date_range("2025-01-01", periods=5, freq="4h", tz="UTC")
    close = np.array([100.0, 101.0, 99.0, 102.0, 98.0])
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
    write_klines(df, tmp_path)
    with pytest.raises(ValueError, match="insufficient klines history"):
        MarketCipherLike(
            MarketCipherLikeConfig(
                instrument_id=_INSTRUMENT_ID,
                bar_type=_BAR_TYPE_4H,
                data_dir=str(tmp_path),
                timeframe="4h",
            )
        )
