"""CrossAssetMomentumConfig has no safe default reference symbol - same
pattern as src/strategies/ml_filtered.py's model_path: default to None,
reject it loudly in __post_init__ rather than silently picking one.
"""

from __future__ import annotations

import pytest
from nautilus_trader.model.data import BarSpecification, BarType
from nautilus_trader.model.enums import AggregationSource, BarAggregation, PriceType
from nautilus_trader.model.identifiers import InstrumentId

from src.strategies.cross_asset_momentum import CrossAssetMomentumConfig

_TARGET_ID = InstrumentId.from_str("ETHUSDT-PERP.BYBIT")
_TARGET_BAR_TYPE = BarType(
    _TARGET_ID, BarSpecification(4, BarAggregation.HOUR, PriceType.LAST), AggregationSource.EXTERNAL
)
_REFERENCE_ID = InstrumentId.from_str("BTCUSDT-PERP.BYBIT")
_REFERENCE_BAR_TYPE = BarType(
    _REFERENCE_ID,
    BarSpecification(4, BarAggregation.HOUR, PriceType.LAST),
    AggregationSource.EXTERNAL,
)


def test_missing_reference_instrument_id_raises() -> None:
    with pytest.raises(ValueError, match="reference_instrument_id"):
        CrossAssetMomentumConfig(
            instrument_id=_TARGET_ID,
            bar_type=_TARGET_BAR_TYPE,
            reference_bar_type=_REFERENCE_BAR_TYPE,
        )


def test_missing_reference_bar_type_raises() -> None:
    with pytest.raises(ValueError, match="reference_instrument_id"):
        CrossAssetMomentumConfig(
            instrument_id=_TARGET_ID,
            bar_type=_TARGET_BAR_TYPE,
            reference_instrument_id=_REFERENCE_ID,
        )


def test_valid_config_constructs() -> None:
    config = CrossAssetMomentumConfig(
        instrument_id=_TARGET_ID,
        bar_type=_TARGET_BAR_TYPE,
        reference_instrument_id=_REFERENCE_ID,
        reference_bar_type=_REFERENCE_BAR_TYPE,
    )
    assert config.reference_instrument_id == _REFERENCE_ID
    assert config.lookback_bars == 10  # default preserved
