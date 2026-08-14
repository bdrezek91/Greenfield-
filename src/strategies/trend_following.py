"""Simple Trend Following benchmark: enter in the direction of N-bar momentum.

Deliberately simple (raw price momentum, no indicator stack) - see
docs/PHASE_0_ARCHITECTURE_RESEARCH.md section 12: the goal of Phase 5 is a
fair comparison framework, not a large family of trend variants.
"""

from __future__ import annotations

from collections import deque

from nautilus_trader.model.data import Bar
from nautilus_trader.model.enums import OrderSide

from src.strategies.base import BenchmarkStrategyConfig, HoldForBarsStrategy


class TrendFollowingConfig(BenchmarkStrategyConfig, frozen=True):  # type: ignore[call-arg]
    lookback_bars: int = 20


class TrendFollowing(HoldForBarsStrategy):
    def __init__(self, config: TrendFollowingConfig) -> None:
        super().__init__(config)
        self._closes: deque[float] = deque(maxlen=config.lookback_bars + 1)

    def signal(self, bar: Bar) -> OrderSide | None:
        self._closes.append(float(bar.close))
        if len(self._closes) <= self.config.lookback_bars:
            return None  # not enough history yet

        momentum = self._closes[-1] - self._closes[0]
        if momentum > 0:
            return OrderSide.BUY
        if momentum < 0:
            return OrderSide.SELL
        return None
