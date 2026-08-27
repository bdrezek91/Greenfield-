"""Breakout entries confirmed (or vetoed) by market_cipher_like's momentum
histogram - GREENFIELD PROFITABILITY PIVOT tournament items 5/6 ("best
strategy + MC filter" / "best strategy + MC veto"). Not a new standalone
strategy family and not order-flow-based execution filtering (that is a
separate, execution/toxicity concern per the standing instruction) - this
composes two already-implemented, already-tested pieces:

- Entry structure: `src.strategies.breakout.Breakout`'s own N-bar
  high/low channel break, unchanged (same `lookback_bars=20` default that
  was the tournament's best-DSR base strategy - see
  docs/CLAUDE_CODE_CONTINUATION.md's tournament checkpoint).
- Confirmation signal: `src.features.momentum_flow.momentum_money_flow_frame`'s
  `momentum_histogram`, read the exact same causal, as-of-safe way
  `src.strategies.market_cipher_like.MarketCipherLike` already does. Fixed
  to market_cipher_like's FIRST preregistered variant
  (channel_span=9, momentum_span=13, signal_window=4,
  docs/PREREGISTRATION_market_cipher_like.md) - a deliberate, non-cherry-
  picked choice made before running this (not selected for looking good),
  since re-selecting among market_cipher_like's own variants here would
  just be parameter mining one level removed.

Two confirmation modes, `mode` field (not two separate classes - the only
difference is how a MISSING or DISAGREEING histogram reading is handled):

- "filter": require ACTIVE agreement. No histogram reading (warmup) or a
  disagreeing sign means no trade. Strictly more conservative than plain
  Breakout - can only reduce trade count, never add trades.
- "veto": block ONLY on ACTIVE disagreement. No histogram reading is
  treated as "nothing to veto with" and the breakout trade proceeds
  unfiltered; only a strictly opposite-signed histogram blocks it.

Economic rationale (written before running, not after): a breakout that
fires while short-term money-flow-confirmed momentum already points the
other way is exactly the kind of low-quality breakout (a fakeout/false
break against the prevailing intrabar flow) docs/RESEARCH_METHODOLOGY.md's
"don't add indicators just to improve the backtest" guidance would still
permit checking, since this is testing a *specific, pre-stated* economic
claim (momentum confirmation reduces breakout fakeouts) with existing
machinery, not searching for one that works.
"""

from __future__ import annotations

from collections import deque
from pathlib import Path

import pandas as pd
from nautilus_trader.model.data import Bar
from nautilus_trader.model.enums import OrderSide

from src.data.as_of_series import AsOfSeries
from src.data.config import TIMEFRAME_MS
from src.data.storage import read_klines
from src.features.momentum_flow import momentum_money_flow_frame
from src.strategies.base import BenchmarkStrategyConfig, HoldForBarsStrategy

_MODES = ("filter", "veto")


class BreakoutMcConfirmationConfig(BenchmarkStrategyConfig, frozen=True):  # type: ignore[call-arg]
    # No safe default - same reasoning as MarketCipherLikeConfig.data_dir:
    # there is no such thing as "some" data directory.
    data_dir: str = ""
    timeframe: str = ""

    lookback_bars: int = 20
    """Breakout's own frozen default, unchanged."""

    channel_span: int = 9
    momentum_span: int = 13
    signal_window: int = 4
    money_flow_window: int = 14
    """market_cipher_like's first preregistered variant, fixed - see module docstring."""

    mode: str = "filter"

    def __post_init__(self) -> None:
        if not self.data_dir:
            raise ValueError("BreakoutMcConfirmationConfig.data_dir is required")
        if self.timeframe not in TIMEFRAME_MS:
            raise ValueError(
                f"BreakoutMcConfirmationConfig.timeframe unsupported: {self.timeframe!r}"
            )
        if self.lookback_bars <= 1:
            raise ValueError("lookback_bars must exceed one")
        for name, value in (
            ("channel_span", self.channel_span),
            ("momentum_span", self.momentum_span),
            ("signal_window", self.signal_window),
            ("money_flow_window", self.money_flow_window),
        ):
            if value <= 1:
                raise ValueError(f"{name} must exceed one")
        if self.mode not in _MODES:
            raise ValueError(f"mode must be one of {_MODES}, got {self.mode!r}")


class BreakoutMcConfirmation(HoldForBarsStrategy):
    def __init__(self, config: BreakoutMcConfirmationConfig) -> None:
        super().__init__(config)
        self._highs: deque[float] = deque(maxlen=config.lookback_bars)
        self._lows: deque[float] = deque(maxlen=config.lookback_bars)

        symbol = config.instrument_id.symbol.value.removesuffix("-PERP")
        klines = read_klines(Path(config.data_dir), symbol, config.timeframe)
        if klines.empty:
            raise ValueError(f"no historical klines for {symbol}/{config.timeframe}")

        duration = pd.Timedelta(milliseconds=TIMEFRAME_MS[config.timeframe])
        feature_input = klines.sort_values("timestamp").reset_index(drop=True).copy()
        # Shift open-time to true close-time availability before computing
        # any feature - identical to MarketCipherLike/materialize_daily_momentum_flow.
        feature_input["timestamp"] = feature_input["timestamp"] + duration
        feature_input["max_source_timestamp"] = feature_input["timestamp"]

        features = momentum_money_flow_frame(
            feature_input,
            channel_span=config.channel_span,
            momentum_span=config.momentum_span,
            signal_window=config.signal_window,
            money_flow_window=config.money_flow_window,
        )
        if features.empty:
            raise ValueError(f"insufficient klines history for {symbol}/{config.timeframe} warmup")
        self._histogram = AsOfSeries(features, "momentum_histogram")

    def signal(self, bar: Bar) -> OrderSide | None:
        high, low, close = float(bar.high), float(bar.low), float(bar.close)

        if len(self._highs) < self.config.lookback_bars:
            self._highs.append(high)
            self._lows.append(low)
            return None  # not enough history yet

        prior_high = max(self._highs)
        prior_low = min(self._lows)
        self._highs.append(high)
        self._lows.append(low)

        breakout_side: OrderSide | None = None
        if close > prior_high:
            breakout_side = OrderSide.BUY
        elif close < prior_low:
            breakout_side = OrderSide.SELL
        if breakout_side is None:
            return None

        histogram_window = self._histogram.window_ending_at(int(bar.ts_event), 1)
        histogram = float(histogram_window[0]) if len(histogram_window) >= 1 else None

        if self.config.mode == "filter":
            if histogram is None:
                return None
            agrees = histogram > 0.0 if breakout_side == OrderSide.BUY else histogram < 0.0
            return breakout_side if agrees else None
        else:  # "veto"
            if histogram is None:
                return breakout_side
            disagrees = histogram < 0.0 if breakout_side == OrderSide.BUY else histogram > 0.0
            return None if disagrees else breakout_side
