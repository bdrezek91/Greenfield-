"""Family: long/short account-ratio contrarian.

Bybit's long/short account ratio (src.data.long_short_ratio_client,
collected live by scripts/collect_long_short_ratio.py - this endpoint has
no backfill, so history only goes back as far as the collector has been
running) is a direct positioning-crowding signal, distinct from funding
rate: it counts accounts, not leveraged notional. A ratio far from its
recent norm - most accounts long, or most accounts short - is a classic
contrarian (mean-reversion) setup: crowded positioning has less room to
extend and more room to unwind. This mirrors
src.strategies.funding_contrarian's z-score shape but on this different,
independent data source and without an open-interest confirmation filter
(kept deliberately simple - see that module and src.strategies.
mean_reversion for why fewer free parameters matters for this protocol's
require_parameter_stability check).
"""

from __future__ import annotations

from pathlib import Path

from nautilus_trader.model.data import Bar
from nautilus_trader.model.enums import OrderSide

from src.data.as_of_series import AsOfSeries
from src.data.storage import read_long_short_ratio
from src.strategies.base import BenchmarkStrategyConfig, HoldForBarsStrategy


class LongShortRatioContrarianConfig(BenchmarkStrategyConfig, frozen=True):  # type: ignore[call-arg]
    data_dir: str = ""
    period: str = "1h"
    zscore_lookback: int = 30
    zscore_threshold: float = 1.5

    def __post_init__(self) -> None:
        super().__post_init__()
        if not self.data_dir:
            raise ValueError("LongShortRatioContrarianConfig.data_dir is required")
        if self.zscore_lookback < 2:
            raise ValueError("zscore_lookback must be >= 2")
        if self.zscore_threshold <= 0:
            raise ValueError("zscore_threshold must be positive")


class LongShortRatioContrarian(HoldForBarsStrategy):
    def __init__(self, config: LongShortRatioContrarianConfig) -> None:
        super().__init__(config)
        if not config.data_dir:
            raise ValueError("LongShortRatioContrarianConfig.data_dir is required")
        symbol = config.instrument_id.symbol.value.removesuffix("-PERP")
        ratio = read_long_short_ratio(Path(config.data_dir), symbol, config.period)
        if ratio.empty:
            raise ValueError(
                f"no long/short-ratio data on disk for {symbol!r} under {config.data_dir} - "
                "run scripts/collect_long_short_ratio.py first"
            )
        ratio = ratio.assign(ratio=ratio["buy_ratio"] / ratio["sell_ratio"])
        self._ratio = AsOfSeries(ratio, "ratio")

    def signal(self, bar: Bar) -> OrderSide | None:
        ts_ns = int(bar.ts_event)
        window = self._ratio.window_ending_at(ts_ns, self.config.zscore_lookback)
        if len(window) < self.config.zscore_lookback:
            return None
        std = float(window.std())
        if std == 0.0:
            return None
        current = float(window[-1])
        mean = float(window.mean())
        zscore = (current - mean) / std
        if zscore > self.config.zscore_threshold:
            return OrderSide.SELL  # crowded long -> contrarian short
        if zscore < -self.config.zscore_threshold:
            return OrderSide.BUY  # crowded short -> contrarian long
        return None
