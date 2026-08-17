"""Family F: liquidity-sweep price-action reversal, confirmed by rising
open interest.

Rationale: a mechanical, deterministic reading of a popular retail
"smart money concepts" (SMC/ICT) setup - price wicks beyond a recent
swing high/low (commonly framed as a stop-hunt/liquidity grab against
resting orders just past the range) and then closes back inside it (a
rejection, not a genuine breakout). This is the price-action component.

Unlike most SMC material, there is no discretionary "market structure"
judgment here: the swing high/low is a plain N-bar Donchian-style extreme
(same primitive src.strategies.breakout.Breakout uses, but the entry
condition is the OPPOSITE of a breakout - a fade of the wick, not a
follow of the close). "Liquidity sweep + reversal" is deliberately framed
here as a specific, falsifiable rule so it goes through the same walk-
forward/DSR/PBO gate as every other hypothesis, not evaluated by eye on a
chart.

Open interest is used the same way src.strategies.funding_contrarian uses
it: a confirmation filter, not a signal on its own. OI rising alongside
the sweep means real leveraged positioning is being added on the move
that just got rejected (more conviction behind the reversal), rather than
a low-volume wick that reverses for no real reason.
"""

from __future__ import annotations

from collections import deque
from pathlib import Path

from nautilus_trader.model.data import Bar
from nautilus_trader.model.enums import OrderSide

from src.data.as_of_series import AsOfSeries
from src.data.storage import read_open_interest
from src.strategies.base import BenchmarkStrategyConfig, HoldForBarsStrategy


class LiquiditySweepConfluenceConfig(BenchmarkStrategyConfig, frozen=True):  # type: ignore[call-arg]
    # No default would violate msgspec's required-before-optional field
    # order (see src.strategies.funding_contrarian.FundingContrarianConfig
    # for the identical situation) - "" is rejected loudly in __init__.
    data_dir: str = ""
    structure_lookback: int = 20
    oi_interval: str = "1h"
    oi_confirmation_bars: int = 5
    oi_min_change_confirmation: float = 0.0


class LiquiditySweepConfluence(HoldForBarsStrategy):
    def __init__(self, config: LiquiditySweepConfluenceConfig) -> None:
        super().__init__(config)
        if not config.data_dir:
            raise ValueError("LiquiditySweepConfluenceConfig.data_dir is required")

        symbol = config.instrument_id.symbol.value.removesuffix("-PERP")
        open_interest = read_open_interest(Path(config.data_dir), symbol, config.oi_interval)
        if open_interest.empty:
            raise ValueError(
                f"no open-interest data on disk for {symbol!r} under {config.data_dir} - "
                "run scripts/download_funding_oi.py first"
            )
        self._open_interest = AsOfSeries(open_interest, "open_interest")
        self._highs: deque[float] = deque(maxlen=config.structure_lookback)
        self._lows: deque[float] = deque(maxlen=config.structure_lookback)

    def signal(self, bar: Bar) -> OrderSide | None:
        high, low, close = float(bar.high), float(bar.low), float(bar.close)

        if len(self._highs) < self.config.structure_lookback:
            self._highs.append(high)
            self._lows.append(low)
            return None  # not enough history yet to define a swing range

        # Compare against the PRIOR lookback window, then roll it forward -
        # same no-leakage discipline as src.strategies.breakout.Breakout.
        prior_high = max(self._highs)
        prior_low = min(self._lows)
        self._highs.append(high)
        self._lows.append(low)

        # Sweep + rejection: the wick takes out the prior extreme but the
        # close is back inside the range - a failed breakout, the opposite
        # condition to Breakout's close-beyond-extreme entry.
        swept_high = high > prior_high and close < prior_high
        swept_low = low < prior_low and close > prior_low
        if not swept_high and not swept_low:
            return None

        oi_window = self._open_interest.window_ending_at(
            int(bar.ts_event), self.config.oi_confirmation_bars + 1
        )
        if len(oi_window) < 2 or oi_window[0] == 0:
            return None  # not enough OI history yet to confirm
        oi_change = (float(oi_window[-1]) - float(oi_window[0])) / float(oi_window[0])
        if oi_change <= self.config.oi_min_change_confirmation:
            return None  # positions aren't being actively built - no confirmation

        if swept_high:
            return OrderSide.SELL  # liquidity above swept, rejected -> fade down
        return OrderSide.BUY  # liquidity below swept, rejected -> fade up
