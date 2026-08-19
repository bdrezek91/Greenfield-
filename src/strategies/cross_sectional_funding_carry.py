"""Cross-sectional perpetual funding carry: rank the liquid universe by
persistent historical funding rate and go long the most-negative-funding
end (shorts pay longs) while shorting the most-positive-funding end (longs
pay shorts).

Unlike src.strategies.funding_carry (single-asset, absolute threshold),
this is relative: it always holds a position in the extremes of whatever
the universe's funding spread looks like right now, the same
point-in-time-ranking shape as src.strategies.cross_sectional_momentum,
but ranking on funding rate instead of price momentum. Like funding_carry,
this is directional carry with retained price risk, not delta-neutral
cash-and-carry - see that module's docstring for why.

No peer price bars are needed (funding rate is looked up directly from
disk, independent of price), so - unlike cross_sectional_momentum - this
strategy never subscribes to peer bar streams.
"""

from __future__ import annotations

import math
from pathlib import Path

from nautilus_trader.model.data import Bar
from nautilus_trader.model.enums import OrderSide
from nautilus_trader.model.identifiers import InstrumentId

from src.data.as_of_series import AsOfSeries
from src.data.storage import read_funding
from src.strategies.base import BenchmarkStrategyConfig, HoldForBarsStrategy


class CrossSectionalFundingCarryConfig(BenchmarkStrategyConfig, frozen=True):  # type: ignore[call-arg]
    peer_instrument_ids: tuple[InstrumentId, ...] = ()
    data_dir: str = ""
    persistence_observations: int = 6
    top_fraction: float = 0.34

    def __post_init__(self) -> None:
        super().__post_init__()
        if not self.data_dir:
            raise ValueError("CrossSectionalFundingCarryConfig.data_dir is required")
        if not self.peer_instrument_ids:
            raise ValueError("cross-sectional funding carry requires peer_instrument_ids")
        if self.persistence_observations < 2:
            raise ValueError("persistence_observations must be >= 2")
        if not 0 < self.top_fraction <= 0.5:
            raise ValueError("top_fraction must be in (0, 0.5]")


class CrossSectionalFundingCarry(HoldForBarsStrategy):
    def __init__(self, config: CrossSectionalFundingCarryConfig) -> None:
        super().__init__(config)
        data_dir = Path(config.data_dir)
        universe = (config.instrument_id, *config.peer_instrument_ids)
        self._funding: dict[InstrumentId, AsOfSeries] = {}
        for instrument_id in universe:
            symbol = instrument_id.symbol.value.removesuffix("-PERP")
            funding = read_funding(data_dir, symbol)
            if funding.empty:
                raise ValueError(f"no historical funding data for {symbol}")
            self._funding[instrument_id] = AsOfSeries(funding, "funding_rate")

    def signal(self, bar: Bar) -> OrderSide | None:
        ts_ns = int(bar.ts_event)
        rates: dict[InstrumentId, float] = {}
        for instrument_id, series in self._funding.items():
            window = series.window_ending_at(ts_ns, self.config.persistence_observations)
            if len(window) < self.config.persistence_observations:
                return None
            rates[instrument_id] = float(window.mean())

        ordered = sorted(rates, key=rates.get)  # type: ignore[arg-type]
        bucket = max(1, math.ceil(len(ordered) * self.config.top_fraction))
        # Most negative funding first: shorts are paying longs -> be long to receive it.
        if self.config.instrument_id in ordered[:bucket]:
            return OrderSide.BUY
        # Most positive funding last: longs are paying shorts -> be short to receive it.
        if self.config.instrument_id in ordered[-bucket:]:
            return OrderSide.SELL
        return None
