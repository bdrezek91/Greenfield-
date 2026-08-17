"""Family C: funding-rate/open-interest contrarian strategy.

Rationale (mirrors configs/research_protocol.yaml's `funding_oi`
description): an extreme funding rate is a proxy for crowded positioning -
persistently high positive funding means longs are paying shorts heavily to
stay long, a classic over-extended/crowded-long condition; persistently
extreme negative funding is the mirror crowded-short case. Positioning
extremes like this are a textbook contrarian (mean-reversion) setup, not a
trend-following one.

Open interest is used only as a confirmation filter, not a signal on its
own: OI actively rising alongside an extreme funding reading means new
leveraged positions are still being added into the crowd (the squeeze/
unwind, if it comes, has more fuel), whereas extreme funding with flat or
falling OI more likely means the crowd is already unwinding and the edge
this strategy is trying to capture has already happened.

Both funding_rate and open_interest are real historical series
(src/data/storage.py's read_funding/read_open_interest, downloaded via
scripts/download_funding_oi.py) - not a live feed, and not synthesized.
They are lower-frequency than the bars this strategy trades (funding: ~3
readings/day; OI: hourly) and are not shaped like OHLCV bars, so - the
same pattern src.strategies.ml_filtered.MLFiltered uses for its frozen
model artifact - they are loaded directly from disk in __init__ rather
than routed through NautilusTrader's bar-based data engine. Every lookup
is a strict as-of join (most recent reading at or before the bar's
timestamp, never a future one).
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
from nautilus_trader.model.data import Bar
from nautilus_trader.model.enums import OrderSide

from src.data.storage import read_funding, read_open_interest
from src.strategies.base import BenchmarkStrategyConfig, HoldForBarsStrategy


class FundingContrarianConfig(BenchmarkStrategyConfig, frozen=True):  # type: ignore[call-arg]
    # No default would violate msgspec's required-before-optional field
    # order (see src.strategies.ml_filtered.MLFilteredConfig.model_path for
    # the identical situation) - "" is rejected loudly in __init__, a
    # strategy silently reading from the wrong directory is worse.
    data_dir: str = ""
    oi_interval: str = "1h"
    funding_zscore_lookback: int = 30
    funding_zscore_threshold: float = 1.5
    oi_confirmation_bars: int = 5
    oi_min_change_confirmation: float = 0.0  # OI must rise by at least this fraction to confirm


class _AsOfSeries:
    """Strict point-in-time lookup over a sorted (timestamp, value) series -
    never returns a reading from after the queried timestamp."""

    def __init__(self, df: pd.DataFrame, value_col: str) -> None:
        ordered = df.sort_values("timestamp")
        self._timestamps_ns = ordered["timestamp"].to_numpy(dtype="datetime64[ns]").astype("int64")
        self._values = ordered[value_col].to_numpy(dtype=float)

    def __len__(self) -> int:
        return len(self._values)

    def window_ending_at(self, ts_ns: int, n: int) -> np.ndarray:
        idx = int(np.searchsorted(self._timestamps_ns, ts_ns, side="right"))
        return self._values[max(0, idx - n) : idx]


class FundingContrarian(HoldForBarsStrategy):
    def __init__(self, config: FundingContrarianConfig) -> None:
        super().__init__(config)
        if not config.data_dir:
            raise ValueError("FundingContrarianConfig.data_dir is required")

        # Nautilus instrument symbols are "<SYMBOL>-PERP" (see
        # src.backtesting.instruments.instrument_id_for) but funding/OI are
        # stored on disk under the plain Bybit symbol - strip the suffix.
        symbol = config.instrument_id.symbol.value.removesuffix("-PERP")
        data_dir = Path(config.data_dir)
        funding = read_funding(data_dir, symbol)
        open_interest = read_open_interest(data_dir, symbol, config.oi_interval)
        if funding.empty:
            raise ValueError(
                f"no funding-rate data on disk for {symbol!r} under {data_dir} - "
                "run scripts/download_funding_oi.py first"
            )
        if open_interest.empty:
            raise ValueError(
                f"no open-interest data on disk for {symbol!r} under {data_dir} - "
                "run scripts/download_funding_oi.py first"
            )
        self._funding = _AsOfSeries(funding, "funding_rate")
        self._open_interest = _AsOfSeries(open_interest, "open_interest")

    def signal(self, bar: Bar) -> OrderSide | None:
        ts_ns = int(bar.ts_event)

        funding_window = self._funding.window_ending_at(ts_ns, self.config.funding_zscore_lookback)
        if len(funding_window) < self.config.funding_zscore_lookback:
            return None  # not enough funding history yet to form a z-score

        std = float(funding_window.std())
        if std == 0.0:
            return None
        current_funding = float(funding_window[-1])
        mean = float(funding_window.mean())
        zscore = (current_funding - mean) / std

        oi_window = self._open_interest.window_ending_at(
            ts_ns, self.config.oi_confirmation_bars + 1
        )
        if len(oi_window) < 2 or oi_window[0] == 0:
            return None  # not enough OI history yet to confirm
        oi_change = (float(oi_window[-1]) - float(oi_window[0])) / float(oi_window[0])
        if oi_change <= self.config.oi_min_change_confirmation:
            return None  # positions aren't being actively built - no confirmation

        if zscore > self.config.funding_zscore_threshold:
            return OrderSide.SELL  # crowded longs paying heavily -> contrarian short
        if zscore < -self.config.funding_zscore_threshold:
            return OrderSide.BUY  # crowded shorts paying heavily -> contrarian long
        return None
