"""Volatility Expansion family: enter when a bar's range spikes well above its
recent average range, in the direction of that bar's own move.

Structurally different from Momentum/Breakout: the trigger is a volatility
regime shift (range expansion), not the price level or its drift. A common
real-world story: a squeeze resolves into a sharp directional move.
"""

from __future__ import annotations

from collections import deque

from nautilus_trader.model.data import Bar
from nautilus_trader.model.enums import OrderSide

from src.strategies.base import BenchmarkStrategyConfig, HoldForBarsStrategy


class VolatilityExpansionConfig(BenchmarkStrategyConfig, frozen=True):  # type: ignore[call-arg]
    lookback_bars: int = 20
    expansion_multiple: float = 1.5  # current range must exceed this x the recent average range


class VolatilityExpansion(HoldForBarsStrategy):
    def __init__(self, config: VolatilityExpansionConfig) -> None:
        super().__init__(config)
        self._ranges: deque[float] = deque(maxlen=config.lookback_bars)

    def signal(self, bar: Bar) -> OrderSide | None:
        high, low, open_, close = float(bar.high), float(bar.low), float(bar.open), float(
            bar.close
        )
        current_range = high - low

        if len(self._ranges) < self.config.lookback_bars:
            self._ranges.append(current_range)
            return None  # not enough history yet

        # Compare against the PRIOR lookback window's average, then roll it
        # forward - the current bar's own range must not leak into its baseline.
        avg_range = sum(self._ranges) / len(self._ranges)
        self._ranges.append(current_range)

        if avg_range <= 0 or current_range < avg_range * self.config.expansion_multiple:
            return None

        if close > open_:
            return OrderSide.BUY
        if close < open_:
            return OrderSide.SELL
        return None
