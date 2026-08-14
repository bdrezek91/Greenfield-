"""Buy & Hold benchmark: enter once on the first bar, never exit.

Per docs/RESEARCH_METHODOLOGY.md, every strategy is judged against this: if
it can't beat simply holding the instrument, it hasn't demonstrated an edge.
"""

from __future__ import annotations

from nautilus_trader.model.data import Bar, BarType
from nautilus_trader.model.enums import OrderSide
from nautilus_trader.model.identifiers import InstrumentId
from nautilus_trader.trading.strategy import Strategy, StrategyConfig

from src.strategies.sizing import position_size


class BuyAndHoldConfig(StrategyConfig, frozen=True):  # type: ignore[call-arg]
    instrument_id: InstrumentId
    bar_type: BarType
    risk_fraction: float = 0.1


class BuyAndHold(Strategy):
    def __init__(self, config: BuyAndHoldConfig) -> None:
        super().__init__(config)
        self._entered = False

    def on_start(self) -> None:
        self.subscribe_bars(self.config.bar_type)

    def on_bar(self, bar: Bar) -> None:
        if self._entered:
            return

        instrument = self.cache.instrument(self.config.instrument_id)
        if instrument is None:
            return

        equity = self.portfolio.account(instrument.id.venue).balance_total(
            instrument.quote_currency
        )
        quantity = position_size(equity, float(bar.close), self.config.risk_fraction, instrument)
        if quantity.as_double() <= 0:
            return

        self.submit_order(
            self.order_factory.market(self.config.instrument_id, OrderSide.BUY, quantity)
        )
        self._entered = True
