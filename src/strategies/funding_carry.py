"""Directional perpetual funding carry using real point-in-time rates.

This is not delta-neutral spot/perpetual cash-and-carry. It is deliberately
named and reported as directional carry: receive persistently positive
funding by shorting, or persistently negative funding by going long, while
remaining exposed to price risk. A true cash-and-carry test requires spot,
borrow and basis datasets which this repository still does not possess.
"""

from __future__ import annotations

from pathlib import Path

from nautilus_trader.model.data import Bar
from nautilus_trader.model.enums import OrderSide

from src.data.as_of_series import AsOfSeries
from src.data.storage import read_funding
from src.strategies.base import BenchmarkStrategyConfig, HoldForBarsStrategy


class FundingCarryConfig(BenchmarkStrategyConfig, frozen=True):  # type: ignore[call-arg]
    data_dir: str = ""
    persistence_observations: int = 6
    min_abs_funding_rate: float = 0.00005

    def __post_init__(self) -> None:
        super().__post_init__()
        if self.persistence_observations < 2:
            raise ValueError("persistence_observations must be >= 2")
        if self.min_abs_funding_rate <= 0:
            raise ValueError("min_abs_funding_rate must be positive")


class FundingCarry(HoldForBarsStrategy):
    def __init__(self, config: FundingCarryConfig) -> None:
        super().__init__(config)
        if not config.data_dir:
            raise ValueError("FundingCarryConfig.data_dir is required")
        symbol = config.instrument_id.symbol.value.removesuffix("-PERP")
        funding = read_funding(Path(config.data_dir), symbol)
        if funding.empty:
            raise ValueError(f"no historical funding data for {symbol}")
        self._funding = AsOfSeries(funding, "funding_rate")

    def signal(self, bar: Bar) -> OrderSide | None:
        values = self._funding.window_ending_at(
            int(bar.ts_event), self.config.persistence_observations
        )
        if len(values) < self.config.persistence_observations:
            return None
        mean_rate = float(values.mean())
        if mean_rate >= self.config.min_abs_funding_rate and (values > 0).all():
            return OrderSide.SELL
        if mean_rate <= -self.config.min_abs_funding_rate and (values < 0).all():
            return OrderSide.BUY
        return None
