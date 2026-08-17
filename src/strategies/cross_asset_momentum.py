"""Cross-asset/regime confirmation (family B, ETAP 2 of the brief): trade a
target symbol's own momentum signal only when a reference symbol's trend
regime (src.regimes.classifier, rule-based, no AI/ML) agrees with the
signal's direction.

Rationale (see configs/research_protocol.yaml's cross_asset_regime family):
BTC dominates crypto market-wide direction more than any single altcoin's
own price action does. A momentum signal on ETH/SOL that only fires while
BTC is itself in a confirming trend is a different, and arguably more
economically motivated, hypothesis than the same signal in isolation
(src/strategies/momentum.py) - it is testing "does regime confirmation
help", not a new indicator on the same instrument.

Deliberately reuses momentum_signal (src/strategies/signals.py) for the
target's own entry rule rather than inventing a second momentum
implementation - the only new mechanism here is the regime gate.
"""

from __future__ import annotations

from collections import deque

import pandas as pd
from nautilus_trader.model.data import Bar, BarType
from nautilus_trader.model.enums import OrderSide
from nautilus_trader.model.identifiers import InstrumentId

from src.regimes.classifier import RegimeConfig, classify_regimes
from src.strategies.base import BenchmarkStrategyConfig, HoldForBarsStrategy
from src.strategies.signals import momentum_signal


class CrossAssetMomentumConfig(BenchmarkStrategyConfig, frozen=True):  # type: ignore[call-arg]
    # No safe default (there is no such thing as "some" reference
    # instrument/bar type) despite following BenchmarkStrategyConfig's
    # defaulted fields - msgspec.Struct requires required-before-optional
    # field order across the whole inheritance chain, so these can't be
    # made required without reordering the base class. Defaulting to None
    # and rejecting it immediately in __post_init__ (same pattern as
    # src/strategies/ml_filtered.py's model_path) is a loud constructor
    # error instead of a silently wrong config.
    reference_instrument_id: InstrumentId | None = None
    reference_bar_type: BarType | None = None

    lookback_bars: int = 10
    threshold: float = 0.01
    regime_short_ma_period: int = 20
    regime_long_ma_period: int = 50
    regime_adx_period: int = 14
    regime_adx_threshold: float = 25.0

    def __post_init__(self) -> None:
        if self.reference_instrument_id is None or self.reference_bar_type is None:
            raise ValueError(
                "CrossAssetMomentumConfig requires reference_instrument_id and "
                "reference_bar_type - there is no default reference symbol"
            )


class CrossAssetMomentum(HoldForBarsStrategy):
    def __init__(self, config: CrossAssetMomentumConfig) -> None:
        super().__init__(config)
        self._closes: deque[float] = deque(maxlen=config.lookback_bars + 1)
        self._regime_config = RegimeConfig(
            short_ma_period=config.regime_short_ma_period,
            long_ma_period=config.regime_long_ma_period,
            adx_period=config.regime_adx_period,
            adx_trend_threshold=config.regime_adx_threshold,
        )
        # Regime classification needs a rolling window of reference OHLC
        # data, not just closes - long_ma_period + adx_period is the
        # longest indicator warmup involved, plus a small safety margin.
        self._reference_warmup = config.regime_long_ma_period + config.regime_adx_period + 5
        self._reference_bars: deque[dict] = deque(maxlen=self._reference_warmup)
        self._reference_trend_regime: str | None = None

    def on_start(self) -> None:
        super().on_start()  # subscribes to config.bar_type (the target)
        self.subscribe_bars(self.config.reference_bar_type)
        self.log.info(f"Subscribed to reference bars: {self.config.reference_bar_type}")

    def on_bar(self, bar: Bar) -> None:
        if bar.bar_type == self.config.reference_bar_type:
            self._update_reference_regime(bar)
            return
        super().on_bar(bar)

    def _update_reference_regime(self, bar: Bar) -> None:
        self._reference_bars.append(
            {
                "timestamp": pd.Timestamp(bar.ts_event, unit="ns", tz="UTC"),
                "open": float(bar.open),
                "high": float(bar.high),
                "low": float(bar.low),
                "close": float(bar.close),
            }
        )
        if len(self._reference_bars) < self._reference_warmup:
            self._reference_trend_regime = None  # not enough reference history yet
            return
        classified = classify_regimes(pd.DataFrame(self._reference_bars), self._regime_config)
        latest = classified["trend_regime"].iloc[-1]
        self._reference_trend_regime = None if pd.isna(latest) else latest

    def signal(self, bar: Bar) -> OrderSide | None:
        self._closes.append(float(bar.close))
        base_signal = momentum_signal(
            self._closes, self.config.lookback_bars, self.config.threshold
        )
        if base_signal is None:
            return None
        # No reference regime yet (insufficient warmup, or RANGE/unclear) -
        # stay flat rather than guess whether it would have confirmed.
        if base_signal == OrderSide.BUY and self._reference_trend_regime == "UPTREND":
            return OrderSide.BUY
        if base_signal == OrderSide.SELL and self._reference_trend_regime == "DOWNTREND":
            return OrderSide.SELL
        return None
