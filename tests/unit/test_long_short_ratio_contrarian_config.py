"""LongShortRatioContrarianConfig.data_dir has no safe default - same
pattern as src/strategies/funding_contrarian.py's data_dir.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest
from nautilus_trader.model.data import BarSpecification, BarType
from nautilus_trader.model.enums import AggregationSource, BarAggregation, PriceType
from nautilus_trader.model.identifiers import InstrumentId

from src.data.storage import write_long_short_ratio
from src.strategies.long_short_ratio_contrarian import (
    LongShortRatioContrarian,
    LongShortRatioContrarianConfig,
)

_INSTRUMENT_ID = InstrumentId.from_str("BTCUSDT-PERP.BYBIT")
_BAR_TYPE = BarType(
    _INSTRUMENT_ID,
    BarSpecification(4, BarAggregation.HOUR, PriceType.LAST),
    AggregationSource.EXTERNAL,
)


def test_missing_data_dir_raises() -> None:
    with pytest.raises(ValueError, match="data_dir"):
        LongShortRatioContrarian(
            LongShortRatioContrarianConfig(instrument_id=_INSTRUMENT_ID, bar_type=_BAR_TYPE)
        )


def test_missing_ratio_data_on_disk_raises(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="long/short-ratio"):
        LongShortRatioContrarian(
            LongShortRatioContrarianConfig(
                instrument_id=_INSTRUMENT_ID, bar_type=_BAR_TYPE, data_dir=str(tmp_path)
            )
        )


def test_valid_data_constructs(tmp_path: Path) -> None:
    ts = pd.date_range("2025-01-01", periods=50, freq="5min", tz="UTC")
    write_long_short_ratio(
        pd.DataFrame(
            {"timestamp": ts, "symbol": "BTCUSDT", "buy_ratio": 0.55, "sell_ratio": 0.45}
        ),
        tmp_path,
        "5min",
    )
    strategy = LongShortRatioContrarian(
        LongShortRatioContrarianConfig(
            instrument_id=_INSTRUMENT_ID,
            bar_type=_BAR_TYPE,
            data_dir=str(tmp_path),
            period="5min",
        )
    )
    assert len(strategy._ratio) == 50
