"""Breakout family: enter when price breaks the N-bar high/low (Donchian-style channel).

Unlike Momentum/Trend Following (which react to the closing price's drift),
Breakout reacts to price reaching a new extreme relative to recent range -
a structurally different signal, not just a different lookback on the same idea.
"""

from __future__ import annotations

from collections import deque

from nautilus_trader.model.data import Bar
from nautilus_trader.model.enums import OrderSide

from src.strategies.base import BenchmarkStrategyConfig, HoldForBarsStrategy


class BreakoutConfig(BenchmarkStrategyConfig, frozen=True):  # type: ignore[call-arg]
    lookback_bars: int = 20


class Breakout(HoldForBarsStrategy):
    def __init__(self, config: BreakoutConfig) -> None:
        super().__init__(config)
        self._highs: deque[float] = deque(maxlen=config.lookback_bars)
        self._lows: deque[float] = deque(maxlen=config.lookback_bars)

    def signal(self, bar: Bar) -> OrderSide | None:
        high, low, close = float(bar.high), float(bar.low), float(bar.close)

        if len(self._highs) < self.config.lookback_bars:
            self._highs.append(high)
            self._lows.append(low)
            return None  # not enough history yet

        # Compare against the PRIOR lookback window, then roll it forward -
        # the current bar's own high/low must not leak into its own signal.
        prior_high = max(self._highs)
        prior_low = min(self._lows)
        self._highs.append(high)
        self._lows.append(low)

        if close > prior_high:
            return OrderSide.BUY
        if close < prior_low:
            return OrderSide.SELL
        return None
