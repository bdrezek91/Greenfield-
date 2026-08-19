"""Family: funding-aware multi-horizon trend (see
docs/PREREGISTRATION_funding_aware_multi_horizon_trend.md for the frozen
hypothesis, exact rules, parameter grid, and rejection criteria - this
module implements exactly that document, nothing more).

Economic mechanism: a slow trend on perpetual futures may retain positive
expectancy after realistic costs if (1) direction is confirmed on TWO
horizons at once (4h primary, 1d confirming - a single fast signal is
mostly noise; requiring agreement filters some of it without waiting on
the slow horizon alone, which would trade too rarely), (2) position size
scales inversely with volatility (already-existing RiskEngine mechanism,
reused unchanged), and (3) an extreme funding rate acts as a cost VETO on
entry, never a standalone signal: entering the side that would pay
extreme funding has a worse expectancy from the cost alone, independent of
whether the trend itself is real.

Deliberately reuses existing, already-tested mechanisms wherever the
prereg's economics allow it, per the brief's "don't add indicators just to
improve the backtest": `src.strategies.signals.momentum_signal` for both
horizons' directional signal, `HoldForBarsStrategy`'s existing ATR-stop
(`use_atr_exit`) as the exit mechanism and `holding_period_bars` as the
pre-registered max-hold backstop, and `RiskEngine`'s existing
`volatility_target` sizing. The only new mechanism here is (a) the
causal same-symbol dual-timeframe signal agreement (same subscribe-a-
second-BarType pattern already used and tested by
`src.strategies.cross_asset_momentum.CrossAssetMomentum`, here for a
higher timeframe of the SAME instrument instead of a different
instrument) and (b) the funding veto (same real-historical-data,
strict as-of-join pattern already used and tested by
`src.strategies.funding_contrarian.FundingContrarian`).
"""

from __future__ import annotations

from collections import deque
from pathlib import Path

from nautilus_trader.model.data import Bar, BarType
from nautilus_trader.model.enums import OrderSide

from src.data.as_of_series import AsOfSeries
from src.data.storage import read_funding
from src.strategies.base import BenchmarkStrategyConfig, HoldForBarsStrategy
from src.strategies.signals import momentum_signal

# Sign-only signal (no dead zone) on each horizon - see the prereg's
# "Sygnał kierunkowy" section: "Dodatni -> long, ujemny -> short, zero ->
# brak sygnału". Low turnover comes from requiring BOTH horizons to agree,
# the funding veto, and the ATR-stop/holding-period exit - not from an
# entry dead zone, which was deliberately left out of the frozen parameter
# grid to avoid tuning yet another knob against this hypothesis.
_SIGNAL_THRESHOLD = 0.0


class FundingAwareMultiHorizonTrendConfig(BenchmarkStrategyConfig, frozen=True):  # type: ignore[call-arg]
    # No safe default for either (same reasoning as
    # src.strategies.cross_asset_momentum.CrossAssetMomentumConfig's
    # reference_bar_type and src.strategies.funding_contrarian.
    # FundingContrarianConfig's data_dir - there is no such thing as "some"
    # higher timeframe or "some" data directory).
    higher_bar_type: BarType | None = None
    data_dir: str = ""

    lookback_bars_4h: int = 60
    lookback_bars_1d: int = 10
    funding_zscore_lookback: int = 30
    funding_zscore_threshold: float = 2.0

    def __post_init__(self) -> None:
        if self.higher_bar_type is None:
            raise ValueError(
                "FundingAwareMultiHorizonTrendConfig requires higher_bar_type - "
                "there is no default confirming horizon"
            )
        if not self.data_dir:
            raise ValueError("FundingAwareMultiHorizonTrendConfig.data_dir is required")
        if self.lookback_bars_4h < 2:
            raise ValueError("lookback_bars_4h must be >= 2")
        if self.lookback_bars_1d < 2:
            raise ValueError("lookback_bars_1d must be >= 2")
        if self.funding_zscore_lookback < 2:
            raise ValueError("funding_zscore_lookback must be >= 2")
        if self.funding_zscore_threshold <= 0:
            raise ValueError("funding_zscore_threshold must be positive")


class FundingAwareMultiHorizonTrend(HoldForBarsStrategy):
    def __init__(self, config: FundingAwareMultiHorizonTrendConfig) -> None:
        super().__init__(config)
        if config.higher_bar_type is None:
            raise ValueError("FundingAwareMultiHorizonTrendConfig requires higher_bar_type")
        if not config.data_dir:
            raise ValueError("FundingAwareMultiHorizonTrendConfig.data_dir is required")

        self._closes_4h: deque[float] = deque(maxlen=config.lookback_bars_4h + 1)
        self._closes_1d: deque[float] = deque(maxlen=config.lookback_bars_1d + 1)
        # Set only when the confirming (higher-timeframe) bar arrives -
        # i.e. only from information NautilusTrader has already delivered
        # strictly before any 4h bar that reads it (see the prereg's
        # "Przyczynowość" section and tests/data_integrity's truncated-
        # series test for this module).
        self._higher_signal: OrderSide | None = None

        symbol = config.instrument_id.symbol.value.removesuffix("-PERP")
        funding = read_funding(Path(config.data_dir), symbol)
        if funding.empty:
            raise ValueError(f"no historical funding data for {symbol}")
        self._funding = AsOfSeries(funding, "funding_rate")

    def on_start(self) -> None:
        super().on_start()  # subscribes to config.bar_type (4h, the primary)
        self.subscribe_bars(self.config.higher_bar_type)
        self.log.info(f"Subscribed to confirming bars: {self.config.higher_bar_type}")

    def on_bar(self, bar: Bar) -> None:
        if bar.bar_type == self.config.higher_bar_type:
            self._closes_1d.append(float(bar.close))
            self._higher_signal = momentum_signal(
                self._closes_1d, self.config.lookback_bars_1d, _SIGNAL_THRESHOLD
            )
            return
        super().on_bar(bar)

    def signal(self, bar: Bar) -> OrderSide | None:
        self._closes_4h.append(float(bar.close))
        base_signal = momentum_signal(
            self._closes_4h, self.config.lookback_bars_4h, _SIGNAL_THRESHOLD
        )
        if base_signal is None or self._higher_signal is None:
            return None
        if base_signal != self._higher_signal:
            return None  # 4h/1d disagree - no trade, not a tie-break of any kind

        side = base_signal
        if self._funding_vetoes(side, int(bar.ts_event)):
            return None
        return side

    def _funding_vetoes(self, side: OrderSide, ts_ns: int) -> bool:
        """True if extreme historical funding vetoes entering `side` -
        never generates a trade on its own, only blocks one already implied
        by `base_signal`/`_higher_signal` agreeing above.
        """
        window = self._funding.window_ending_at(ts_ns, self.config.funding_zscore_lookback)
        if len(window) < self.config.funding_zscore_lookback:
            return False  # not enough funding history to judge "extreme" - don't veto on ignorance
        std = float(window.std())
        if std == 0.0:
            return False
        zscore = (float(window[-1]) - float(window.mean())) / std
        if side == OrderSide.BUY and zscore > self.config.funding_zscore_threshold:
            return True  # longs would pay an extreme rate
        if side == OrderSide.SELL and zscore < -self.config.funding_zscore_threshold:
            return True  # shorts would pay an extreme rate
        return False
