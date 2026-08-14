"""Random Entry benchmark: seeded-random long/short direction.

Per docs/RESEARCH_METHODOLOGY.md's section on benchmarks, this is the
sanity check every other strategy has to beat - if a strategy can't
outperform coin-flip entries under identical position sizing and holding
period, it hasn't demonstrated a real edge.
"""

from __future__ import annotations

import random

from nautilus_trader.model.data import Bar
from nautilus_trader.model.enums import OrderSide

from src.strategies.base import BenchmarkStrategyConfig, HoldForBarsStrategy


class RandomEntryConfig(BenchmarkStrategyConfig, frozen=True):  # type: ignore[call-arg]
    seed: int = 42


class RandomEntry(HoldForBarsStrategy):
    def __init__(self, config: RandomEntryConfig) -> None:
        super().__init__(config)
        self._rng = random.Random(config.seed)

    def signal(self, bar: Bar) -> OrderSide | None:
        return self._rng.choice([OrderSide.BUY, OrderSide.SELL])
