"""FundingContrarianConfig.data_dir has no safe default (same pattern as
src/strategies/ml_filtered.py's model_path) - validated loudly in
FundingContrarian.__init__, not silently defaulted to "./data" or similar.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest
from nautilus_trader.model.data import BarSpecification, BarType
from nautilus_trader.model.enums import AggregationSource, BarAggregation, PriceType
from nautilus_trader.model.identifiers import InstrumentId

from src.data.storage import write_funding, write_open_interest
from src.strategies.funding_contrarian import FundingContrarian, FundingContrarianConfig

_INSTRUMENT_ID = InstrumentId.from_str("BTCUSDT-PERP.BYBIT")
_BAR_TYPE = BarType(
    _INSTRUMENT_ID,
    BarSpecification(4, BarAggregation.HOUR, PriceType.LAST),
    AggregationSource.EXTERNAL,
)


def test_missing_data_dir_raises() -> None:
    with pytest.raises(ValueError, match="data_dir"):
        FundingContrarian(FundingContrarianConfig(instrument_id=_INSTRUMENT_ID, bar_type=_BAR_TYPE))


def test_missing_funding_data_on_disk_raises(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="funding-rate"):
        FundingContrarian(
            FundingContrarianConfig(
                instrument_id=_INSTRUMENT_ID, bar_type=_BAR_TYPE, data_dir=str(tmp_path)
            )
        )


def test_missing_open_interest_data_on_disk_raises(tmp_path: Path) -> None:
    ts = pd.date_range("2025-01-01", periods=40, freq="8h", tz="UTC")
    write_funding(
        pd.DataFrame({"timestamp": ts, "symbol": "BTCUSDT", "funding_rate": 0.0001}), tmp_path
    )
    with pytest.raises(ValueError, match="open-interest"):
        FundingContrarian(
            FundingContrarianConfig(
                instrument_id=_INSTRUMENT_ID, bar_type=_BAR_TYPE, data_dir=str(tmp_path)
            )
        )


def test_valid_data_constructs(tmp_path: Path) -> None:
    funding_ts = pd.date_range("2025-01-01", periods=40, freq="8h", tz="UTC")
    write_funding(
        pd.DataFrame({"timestamp": funding_ts, "symbol": "BTCUSDT", "funding_rate": 0.0001}),
        tmp_path,
    )
    oi_ts = pd.date_range("2025-01-01", periods=100, freq="1h", tz="UTC")
    write_open_interest(
        pd.DataFrame({"timestamp": oi_ts, "symbol": "BTCUSDT", "open_interest": 1000.0}),
        tmp_path,
        "1h",
    )
    strategy = FundingContrarian(
        FundingContrarianConfig(
            instrument_id=_INSTRUMENT_ID, bar_type=_BAR_TYPE, data_dir=str(tmp_path)
        )
    )
    assert len(strategy._funding) == 40
    assert len(strategy._open_interest) == 100
