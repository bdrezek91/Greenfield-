"""CrossSectionalFundingCarryConfig.data_dir/peer_instrument_ids have no
safe default - same pattern as src/strategies/funding_contrarian.py's
data_dir.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest
from nautilus_trader.model.data import BarSpecification, BarType
from nautilus_trader.model.enums import AggregationSource, BarAggregation, PriceType
from nautilus_trader.model.identifiers import InstrumentId

from src.data.storage import write_funding
from src.strategies.cross_sectional_funding_carry import (
    CrossSectionalFundingCarry,
    CrossSectionalFundingCarryConfig,
)

_TARGET_ID = InstrumentId.from_str("BTCUSDT-PERP.BYBIT")
_TARGET_BAR_TYPE = BarType(
    _TARGET_ID, BarSpecification(4, BarAggregation.HOUR, PriceType.LAST), AggregationSource.EXTERNAL
)
_PEER_IDS = (
    InstrumentId.from_str("ETHUSDT-PERP.BYBIT"),
    InstrumentId.from_str("SOLUSDT-PERP.BYBIT"),
)


def test_missing_data_dir_raises() -> None:
    with pytest.raises(ValueError, match="data_dir"):
        CrossSectionalFundingCarryConfig(
            instrument_id=_TARGET_ID, bar_type=_TARGET_BAR_TYPE, peer_instrument_ids=_PEER_IDS
        )


def test_missing_peers_raises(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="peer_instrument_ids"):
        CrossSectionalFundingCarryConfig(
            instrument_id=_TARGET_ID, bar_type=_TARGET_BAR_TYPE, data_dir=str(tmp_path)
        )


def test_missing_funding_data_on_disk_raises(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="no historical funding data"):
        CrossSectionalFundingCarry(
            CrossSectionalFundingCarryConfig(
                instrument_id=_TARGET_ID,
                bar_type=_TARGET_BAR_TYPE,
                data_dir=str(tmp_path),
                peer_instrument_ids=_PEER_IDS,
            )
        )


def test_valid_data_constructs_series_for_target_and_every_peer(tmp_path: Path) -> None:
    ts = pd.date_range("2025-01-01", periods=40, freq="8h", tz="UTC")
    for symbol in ("BTCUSDT", "ETHUSDT", "SOLUSDT"):
        write_funding(
            pd.DataFrame({"timestamp": ts, "symbol": symbol, "funding_rate": 0.0001}), tmp_path
        )
    strategy = CrossSectionalFundingCarry(
        CrossSectionalFundingCarryConfig(
            instrument_id=_TARGET_ID,
            bar_type=_TARGET_BAR_TYPE,
            data_dir=str(tmp_path),
            peer_instrument_ids=_PEER_IDS,
        )
    )
    assert set(strategy._funding) == {_TARGET_ID, *_PEER_IDS}
    assert all(len(series) == 40 for series in strategy._funding.values())
