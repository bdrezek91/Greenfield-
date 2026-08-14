"""Convert canonical OHLCV klines (src.data.schema) into NautilusTrader Bar objects."""

from __future__ import annotations

import pandas as pd
from nautilus_trader.model.data import Bar, BarSpecification, BarType
from nautilus_trader.model.enums import AggregationSource, BarAggregation, PriceType
from nautilus_trader.model.instruments import Instrument
from nautilus_trader.persistence.wranglers import BarDataWrangler

# Canonical timeframe label -> (step, BarAggregation)
_TIMEFRAME_SPEC: dict[str, tuple[int, int]] = {
    "1m": (1, BarAggregation.MINUTE),
    "5m": (5, BarAggregation.MINUTE),
    "15m": (15, BarAggregation.MINUTE),
    "1h": (1, BarAggregation.HOUR),
    "4h": (4, BarAggregation.HOUR),
    "1d": (1, BarAggregation.DAY),
}


def bar_type_for(instrument: Instrument, timeframe: str) -> BarType:
    if timeframe not in _TIMEFRAME_SPEC:
        raise ValueError(f"unsupported timeframe: {timeframe!r}")
    step, aggregation = _TIMEFRAME_SPEC[timeframe]
    bar_spec = BarSpecification(step, aggregation, PriceType.LAST)
    return BarType(instrument.id, bar_spec, AggregationSource.EXTERNAL)


def klines_to_bars(df: pd.DataFrame, instrument: Instrument, timeframe: str) -> list[Bar]:
    """Convert a klines DataFrame (src.data.schema.COLUMNS) into a sorted list of Bars.

    The caller is responsible for validating the frame first
    (src.data.validate) - this function assumes clean, gap-free, UTC input.
    """
    if df.empty:
        return []

    bar_type = bar_type_for(instrument, timeframe)
    wrangler = BarDataWrangler(bar_type=bar_type, instrument=instrument)

    ohlcv = df.set_index("timestamp")[["open", "high", "low", "close", "volume"]].sort_index()
    return wrangler.process(ohlcv)
