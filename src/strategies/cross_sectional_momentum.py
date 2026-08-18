"""Point-in-time cross-sectional momentum over a fixed liquid universe.

Every rank uses observations strictly earlier than the target bar event.
This one-bar synchronization lag makes the result deterministic regardless
of the engine's ordering of equal-timestamp bars across instruments.
"""

from __future__ import annotations

import math
from collections import deque

from nautilus_trader.model.data import Bar, BarType
from nautilus_trader.model.enums import OrderSide
from nautilus_trader.model.identifiers import InstrumentId

from src.strategies.base import BenchmarkStrategyConfig, HoldForBarsStrategy


class CrossSectionalMomentumConfig(BenchmarkStrategyConfig, frozen=True):  # type: ignore[call-arg]
    peer_instrument_ids: tuple[InstrumentId, ...] = ()
    peer_bar_types: tuple[BarType, ...] = ()
    lookback_bars: int = 30
    top_fraction: float = 0.34
    long_short: bool = True

    def __post_init__(self) -> None:
        super().__post_init__()
        if self.lookback_bars < 2:
            raise ValueError("lookback_bars must be >= 2")
        if not self.peer_instrument_ids or len(self.peer_instrument_ids) != len(
            self.peer_bar_types
        ):
            raise ValueError("cross-sectional momentum requires matching peer instruments/bars")
        if not 0 < self.top_fraction <= 0.5:
            raise ValueError("top_fraction must be in (0, 0.5]")


class CrossSectionalMomentum(HoldForBarsStrategy):
    def __init__(self, config: CrossSectionalMomentumConfig) -> None:
        super().__init__(config)
        self._history: dict[BarType, deque[tuple[int, float]]] = {
            config.bar_type: deque(maxlen=config.lookback_bars + 1),
            **{
                bar_type: deque(maxlen=config.lookback_bars + 1)
                for bar_type in config.peer_bar_types
            },
        }

    def on_start(self) -> None:
        super().on_start()
        for bar_type in self.config.peer_bar_types:
            self.subscribe_bars(bar_type)

    def on_bar(self, bar: Bar) -> None:
        if bar.bar_type != self.config.bar_type:
            self._history[bar.bar_type].append((int(bar.ts_event), float(bar.close)))
            return
        super().on_bar(bar)

    def signal(self, bar: Bar) -> OrderSide | None:
        ts_ns = int(bar.ts_event)
        target_history = self._history[self.config.bar_type]
        momenta: dict[BarType, float] = {}
        try:
            for bar_type, history in self._history.items():
                prior = [close for timestamp, close in history if timestamp < ts_ns]
                first_index = -self.config.lookback_bars - 1
                if len(prior) < self.config.lookback_bars + 1 or prior[first_index] == 0:
                    return None
                first = prior[first_index]
                momenta[bar_type] = prior[-1] / first - 1

            ordered = sorted(momenta, key=momenta.get)  # type: ignore[arg-type]
            bucket = max(1, math.ceil(len(ordered) * self.config.top_fraction))
            if self.config.bar_type in ordered[-bucket:]:
                return OrderSide.BUY
            if self.config.long_short and self.config.bar_type in ordered[:bucket]:
                return OrderSide.SELL
            return None
        finally:
            target_history.append((ts_ns, float(bar.close)))
