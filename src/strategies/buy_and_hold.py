"""Buy & Hold benchmark: enter once on the first bar, never exit.

Per docs/RESEARCH_METHODOLOGY.md, every strategy is judged against this: if
it can't beat simply holding the instrument, it hasn't demonstrated an edge.
"""

from __future__ import annotations

import random

from nautilus_trader.model.data import Bar, BarType
from nautilus_trader.model.enums import OrderSide
from nautilus_trader.model.identifiers import InstrumentId
from nautilus_trader.trading.strategy import Strategy, StrategyConfig

from src.risk.engine import RiskConfig, RiskEngine


class BuyAndHoldConfig(StrategyConfig, frozen=True):  # type: ignore[call-arg]
    instrument_id: InstrumentId
    bar_type: BarType
    risk_per_trade: float = 0.1
    max_leverage: float = 10.0
    entry_delay_bars: int = 1
    missed_trade_probability: float = 0.0
    execution_seed: int = 42

    def __post_init__(self) -> None:
        if self.entry_delay_bars < 0:
            raise ValueError("entry_delay_bars must be non-negative")
        if not 0.0 <= self.missed_trade_probability <= 1.0:
            raise ValueError("missed_trade_probability must be in [0, 1]")


class BuyAndHold(Strategy):
    def __init__(self, config: BuyAndHoldConfig) -> None:
        super().__init__(config)
        self._entered = False
        self._signal_seen = False
        self._remaining_delay = config.entry_delay_bars
        self._execution_rng = random.Random(config.execution_seed)
        # Only ever one trade, so max_portfolio_risk == risk_per_trade imposes
        # no extra constraint on it (same reasoning as BenchmarkStrategyConfig).
        self._risk_engine = RiskEngine(
            RiskConfig(
                risk_per_trade=config.risk_per_trade,
                max_portfolio_risk=config.risk_per_trade,
                max_concurrent_positions=1,
                max_leverage=config.max_leverage,
            )
        )

    def on_start(self) -> None:
        self.subscribe_bars(self.config.bar_type)

    def on_bar(self, bar: Bar) -> None:
        if self._entered:
            return

        if not self._signal_seen:
            self._signal_seen = True
            if self._execution_rng.random() < self.config.missed_trade_probability:
                self._entered = True
                return
        if self._remaining_delay > 0:
            self._remaining_delay -= 1
            return

        instrument = self.cache.instrument(self.config.instrument_id)
        if instrument is None:
            return

        equity = self.portfolio.account(instrument.id.venue).balance_total(
            instrument.quote_currency
        )
        decision = self._risk_engine.evaluate(
            instrument=instrument,
            price=float(bar.close),
            equity=equity.as_double(),
            now=self.clock.utc_now(),
        )
        if not decision.approved:
            return

        self.submit_order(
            self.order_factory.market(self.config.instrument_id, OrderSide.BUY, decision.quantity)
        )
        self._entered = True
