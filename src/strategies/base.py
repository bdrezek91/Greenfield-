"""Shared plumbing for the benchmark strategies (Random Entry, Trend Following,
Mean Reversion): fixed-fraction sizing and a common hold-for-N-bars exit rule.

Isolating sizing and exit timing into one shared base means the only thing
that differs between these benchmarks is the entry signal - which is the
honest, apples-to-apples comparison docs/RESEARCH_METHODOLOGY.md calls for.
Buy & Hold doesn't use this base: it has no exit rule by design.
"""

from __future__ import annotations

from abc import abstractmethod

from nautilus_trader.model.data import Bar, BarType
from nautilus_trader.model.enums import OrderSide
from nautilus_trader.model.identifiers import InstrumentId
from nautilus_trader.trading.strategy import Strategy, StrategyConfig

from src.strategies.sizing import position_size


class BenchmarkStrategyConfig(StrategyConfig, frozen=True):  # type: ignore[call-arg]
    instrument_id: InstrumentId
    bar_type: BarType
    risk_fraction: float = 0.1
    holding_period_bars: int = 24


class HoldForBarsStrategy(Strategy):
    """Enter per `signal()` when flat, hold for `holding_period_bars` bars, exit, repeat."""

    def __init__(self, config: BenchmarkStrategyConfig) -> None:
        super().__init__(config)
        self._bars_in_position = 0

    def on_start(self) -> None:
        self.subscribe_bars(self.config.bar_type)

    def on_bar(self, bar: Bar) -> None:
        instrument = self.cache.instrument(self.config.instrument_id)
        if instrument is None:
            return

        if not self.portfolio.is_flat(self.config.instrument_id):
            self._bars_in_position += 1
            if self._bars_in_position >= self.config.holding_period_bars:
                self.close_all_positions(self.config.instrument_id)
                self._bars_in_position = 0
            return

        side = self.signal(bar)
        if side is None:
            return

        equity = self.portfolio.account(instrument.id.venue).balance_total(
            instrument.quote_currency
        )
        quantity = position_size(equity, float(bar.close), self.config.risk_fraction, instrument)
        if quantity.as_double() <= 0:
            return

        self.submit_order(self.order_factory.market(self.config.instrument_id, side, quantity))
        self._bars_in_position = 0

    @abstractmethod
    def signal(self, bar: Bar) -> OrderSide | None:
        """Return BUY/SELL to enter on this bar, or None to stay flat."""
