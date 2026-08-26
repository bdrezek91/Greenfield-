"""Family: Market-Cipher-like momentum/money-flow (see
docs/PREREGISTRATION_market_cipher_like.md for the frozen hypothesis, exact
rules, parameter grid, and rejection criteria - this module implements
exactly that document, nothing more).

Independent, original composition (see
`src.features.momentum_flow.momentum_money_flow_frame`'s own docstring: no
proprietary Market Cipher code or private formula). Entry fires on an
EMA-normalized momentum-wave/signal crossover confirmed by rolling
money-flow direction - one Market-Cipher-like confirmation family, not two
independent votes (money_flow is derived from the same frame as the
crossover it confirms).

Reuses existing, already-tested mechanisms wherever possible, per the
brief's "don't add indicators just to improve the backtest":
`HoldForBarsStrategy`'s existing holding-period/ATR-stop exit and
`RiskEngine`'s existing volatility-target sizing. The only new mechanism is
reading the strategy's own klines history once at construction, shifting
timestamps to true close-time availability (identical to
`src.features.bar_materialization.materialize_daily_momentum_flow`), and
looking up the precomputed, point-in-time-safe feature frame via
`src.data.as_of_series.AsOfSeries` - the same as-of pattern already used and
tested by `src.strategies.funding_contrarian.FundingContrarian`.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd
from nautilus_trader.model.data import Bar
from nautilus_trader.model.enums import OrderSide

from src.data.as_of_series import AsOfSeries
from src.data.config import TIMEFRAME_MS
from src.data.storage import read_klines
from src.features.momentum_flow import momentum_money_flow_frame
from src.strategies.base import BenchmarkStrategyConfig, HoldForBarsStrategy


class MarketCipherLikeConfig(BenchmarkStrategyConfig, frozen=True):  # type: ignore[call-arg]
    # No safe default - same reasoning as
    # src.strategies.funding_contrarian.FundingContrarianConfig.data_dir:
    # there is no such thing as "some" data directory.
    data_dir: str = ""
    # No safe default - the strategy needs the exact klines timeframe label
    # ("4h", "1d", ...) to shift candle-open timestamps to their true
    # close-time availability; `config.bar_type` alone doesn't expose this
    # as a plain string.
    timeframe: str = ""

    channel_span: int = 10
    momentum_span: int = 21
    signal_window: int = 4
    money_flow_window: int = 14
    rsi_window: int = 14
    pivot_left: int = 2
    pivot_right: int = 2

    def __post_init__(self) -> None:
        if not self.data_dir:
            raise ValueError("MarketCipherLikeConfig.data_dir is required")
        if self.timeframe not in TIMEFRAME_MS:
            raise ValueError(f"MarketCipherLikeConfig.timeframe unsupported: {self.timeframe!r}")
        for name, value in (
            ("channel_span", self.channel_span),
            ("momentum_span", self.momentum_span),
            ("signal_window", self.signal_window),
            ("money_flow_window", self.money_flow_window),
            ("rsi_window", self.rsi_window),
        ):
            if value <= 1:
                raise ValueError(f"{name} must exceed one")
        if self.pivot_left < 1 or self.pivot_right < 1:
            raise ValueError("pivot_left/pivot_right must be >= 1")


class MarketCipherLike(HoldForBarsStrategy):
    def __init__(self, config: MarketCipherLikeConfig) -> None:
        super().__init__(config)
        symbol = config.instrument_id.symbol.value.removesuffix("-PERP")
        klines = read_klines(Path(config.data_dir), symbol, config.timeframe)
        if klines.empty:
            raise ValueError(f"no historical klines for {symbol}/{config.timeframe}")

        duration = pd.Timedelta(milliseconds=TIMEFRAME_MS[config.timeframe])
        feature_input = klines.sort_values("timestamp").reset_index(drop=True).copy()
        # Shift open-time to true close-time availability before computing
        # any feature - identical to
        # src.features.bar_materialization.materialize_daily_momentum_flow.
        feature_input["timestamp"] = feature_input["timestamp"] + duration
        feature_input["max_source_timestamp"] = feature_input["timestamp"]

        features = momentum_money_flow_frame(
            feature_input,
            channel_span=config.channel_span,
            momentum_span=config.momentum_span,
            signal_window=config.signal_window,
            money_flow_window=config.money_flow_window,
            rsi_window=config.rsi_window,
            pivot_left=config.pivot_left,
            pivot_right=config.pivot_right,
        )
        if features.empty:
            raise ValueError(
                f"insufficient klines history for {symbol}/{config.timeframe} warmup"
            )
        self._histogram = AsOfSeries(features, "momentum_histogram")
        self._money_flow = AsOfSeries(features, "money_flow")

    def signal(self, bar: Bar) -> OrderSide | None:
        ts_ns = int(bar.ts_event)
        histogram_window = self._histogram.window_ending_at(ts_ns, 2)
        if len(histogram_window) < 2:
            return None  # not enough warmed-up feature history yet - stay flat
        previous, current = float(histogram_window[0]), float(histogram_window[1])
        money_flow_window = self._money_flow.window_ending_at(ts_ns, 1)
        if len(money_flow_window) < 1:
            return None
        money_flow = float(money_flow_window[0])

        crossed_up = previous <= 0.0 and current > 0.0
        crossed_down = previous >= 0.0 and current < 0.0
        if crossed_up and money_flow > 0.0:
            return OrderSide.BUY
        if crossed_down and money_flow < 0.0:
            return OrderSide.SELL
        return None
