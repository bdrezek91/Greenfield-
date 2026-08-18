"""Convert canonical OHLCV klines (src.data.schema) into NautilusTrader Bar objects."""

from __future__ import annotations

import numpy as np
import pandas as pd
from nautilus_trader.model.data import Bar, BarSpecification, BarType
from nautilus_trader.model.enums import AggregationSource, BarAggregation, PriceType
from nautilus_trader.model.instruments import Instrument
from nautilus_trader.persistence.wranglers import BarDataWrangler

from src.data.config import TIMEFRAME_MS

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

    # Bybit's kline timestamp is the bar OPEN time.  A completed external
    # bar must not enter the event stream until its CLOSE time, otherwise a
    # strategy receives that bar's high/low/close/volume one full interval
    # too early.  Nautilus' wrangler uses the DataFrame index for both
    # ``ts_event`` and ``ts_init``, so indexing by close time gives the
    # correct information-availability semantics.
    close_time = pd.to_datetime(df["timestamp"], utc=True) + timeframe_delta(timeframe)
    ohlcv = pd.DataFrame(
        {
            col: np.array(df[col], dtype=np.float64, copy=True)
            for col in ("open", "high", "low", "close", "volume")
        },
        index=pd.DatetimeIndex(close_time),
    )
    ohlcv = ohlcv.sort_index()
    return wrangler.process(ohlcv)


def timeframe_delta(timeframe: str) -> pd.Timedelta:
    if timeframe not in TIMEFRAME_MS:
        raise ValueError(f"unsupported timeframe: {timeframe!r}")
    return pd.Timedelta(milliseconds=TIMEFRAME_MS[timeframe])


def closed_klines(df: pd.DataFrame, timeframe: str, as_of: pd.Timestamp) -> pd.DataFrame:
    """Return only bars whose complete OHLCV was available by ``as_of``."""
    if df.empty:
        return df.copy()
    cutoff = pd.Timestamp(as_of)
    if cutoff.tzinfo is None:
        cutoff = cutoff.tz_localize("UTC")
    else:
        cutoff = cutoff.tz_convert("UTC")
    close_time = pd.to_datetime(df["timestamp"], utc=True) + timeframe_delta(timeframe)
    return df.loc[close_time <= cutoff].copy().reset_index(drop=True)
