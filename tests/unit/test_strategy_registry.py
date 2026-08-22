"""The generic CLI registry constructs only compatible, recordable strategies."""

from __future__ import annotations

import pytest
from nautilus_trader.model.data import BarSpecification, BarType
from nautilus_trader.model.enums import AggregationSource, BarAggregation, PriceType
from nautilus_trader.model.identifiers import InstrumentId
from nautilus_trader.trading.strategy import Strategy

from src.strategies.registry import ALL_STRATEGIES, build_registered_strategy

INSTRUMENT_ID = InstrumentId.from_str("BTCUSDT-PERP.BYBIT")
BAR_TYPE = BarType(
    INSTRUMENT_ID,
    BarSpecification(1, BarAggregation.HOUR, PriceType.LAST),
    AggregationSource.EXTERNAL,
)


@pytest.mark.parametrize("name", sorted(ALL_STRATEGIES))
def test_registered_strategy_is_constructible_and_recordable(name: str) -> None:
    strategy = build_registered_strategy(
        name,
        instrument_id=INSTRUMENT_ID,
        bar_type=BAR_TYPE,
    )

    assert isinstance(strategy, Strategy)
    assert hasattr(strategy, "session_recorder")


def test_unknown_generic_strategy_is_rejected() -> None:
    with pytest.raises(ValueError, match="unknown generic strategy"):
        build_registered_strategy(
            "not-registered",
            instrument_id=INSTRUMENT_ID,
            bar_type=BAR_TYPE,
        )
