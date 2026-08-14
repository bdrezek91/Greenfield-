"""Momentum family: enter only when N-bar price change exceeds a threshold.

Distinct from src/strategies/trend_following.py, which trades on any sign of
momentum (even a hair above/below zero). Momentum adds a dead zone -
threshold is a fraction (e.g. 0.01 = 1% over `lookback_bars`) below which no
signal fires - modeling the idea that weak drift isn't worth trading, only a
meaningfully strong move is.
"""

from __future__ import annotations

from collections import deque

from nautilus_trader.model.data import Bar
from nautilus_trader.model.enums import OrderSide

from src.strategies.base import BenchmarkStrategyConfig, HoldForBarsStrategy


class MomentumConfig(BenchmarkStrategyConfig, frozen=True):  # type: ignore[call-arg]
    lookback_bars: int = 10
    threshold: float = 0.01  # minimum fractional change over lookback_bars to trigger


class Momentum(HoldForBarsStrategy):
    def __init__(self, config: MomentumConfig) -> None:
        super().__init__(config)
        self._closes: deque[float] = deque(maxlen=config.lookback_bars + 1)

    def signal(self, bar: Bar) -> OrderSide | None:
        self._closes.append(float(bar.close))
        if len(self._closes) <= self.config.lookback_bars:
            return None  # not enough history yet

        change = (self._closes[-1] - self._closes[0]) / self._closes[0]
        if change > self.config.threshold:
            return OrderSide.BUY
        if change < -self.config.threshold:
            return OrderSide.SELL
        return None
