"""Simple Mean Reversion benchmark: fade extensions away from a moving average.

Deliberately simple (SMA + fixed threshold, no indicator stack) - see
docs/PHASE_0_ARCHITECTURE_RESEARCH.md section 12: the goal of Phase 5 is a
fair comparison framework, not a large family of mean-reversion variants.
"""

from __future__ import annotations

from collections import deque

from nautilus_trader.model.data import Bar
from nautilus_trader.model.enums import OrderSide

from src.strategies.base import BenchmarkStrategyConfig, HoldForBarsStrategy


class MeanReversionConfig(BenchmarkStrategyConfig, frozen=True):  # type: ignore[call-arg]
    lookback_bars: int = 20
    threshold: float = 0.02  # fraction deviation from the moving average that triggers entry


class MeanReversion(HoldForBarsStrategy):
    def __init__(self, config: MeanReversionConfig) -> None:
        super().__init__(config)
        self._closes: deque[float] = deque(maxlen=config.lookback_bars)

    def signal(self, bar: Bar) -> OrderSide | None:
        self._closes.append(float(bar.close))
        if len(self._closes) < self.config.lookback_bars:
            return None  # not enough history yet

        sma = sum(self._closes) / len(self._closes)
        deviation = (float(bar.close) - sma) / sma
        if deviation > self.config.threshold:
            return OrderSide.SELL  # extended above the average -> bet on reversion down
        if deviation < -self.config.threshold:
            return OrderSide.BUY  # extended below the average -> bet on reversion up
        return None
