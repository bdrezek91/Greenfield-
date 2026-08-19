"""Shared plumbing for the benchmark strategies (Random Entry, Trend Following,
Mean Reversion): a common hold-for-N-bars exit rule, with entry approval and
sizing delegated to the risk engine (src/risk/engine.py, Phase 9).

Isolating exit timing and risk handling into one shared base means the only
thing that differs between these strategies is the entry signal - which is
the honest, apples-to-apples comparison docs/RESEARCH_METHODOLOGY.md calls
for. Buy & Hold doesn't use this base: it has no exit rule by design.
"""

from __future__ import annotations

from abc import abstractmethod
from collections import deque

import pandas as pd
from nautilus_trader.model.data import Bar, BarType
from nautilus_trader.model.enums import OrderSide
from nautilus_trader.model.events import OrderFilled, OrderRejected, PositionClosed
from nautilus_trader.model.identifiers import InstrumentId
from nautilus_trader.trading.strategy import Strategy, StrategyConfig

from src.execution.intent import IntentSide, OrderIntent
from src.execution.session_recorder import SessionRecorder
from src.regimes import indicators
from src.risk.engine import RiskConfig, RiskEngine


class BenchmarkStrategyConfig(StrategyConfig, frozen=True):  # type: ignore[call-arg]
    instrument_id: InstrumentId
    bar_type: BarType
    holding_period_bars: int = 24

    # Risk engine parameters (src/risk/engine.py:RiskConfig). Defaults are
    # chosen to reproduce the pre-Phase-9 fixed-10%-of-equity behavior for a
    # strategy's first trade in a fresh backtest (no open positions, no
    # daily loss, no drawdown yet): risk_per_trade=0.1 with a
    # max_portfolio_risk >= 0.1 imposes no additional constraint on that
    # first trade.
    risk_per_trade: float = 0.1
    max_portfolio_risk: float = 0.5
    max_daily_loss: float = 0.5
    max_drawdown: float = 0.5
    max_concurrent_positions: int = 1
    max_leverage: float = 10.0
    volatility_target: float | None = None
    vol_lookback_bars: int = 20

    # Session filter (UTC hours, [start, end)), for a day-trading variant:
    # None (default) = trade any hour, unchanged pre-existing behavior.
    # When set, NEW entries are only taken inside the window, and any open
    # position is force-flattened the first bar outside it - the defining
    # day-trading property (no overnight/cross-session exposure), not just
    # a filter on when to look for signals. start > end wraps midnight
    # (e.g. start=22, end=6 for an Asia-session window); start == end is
    # rejected (an empty or full-day window is ambiguous - use None instead).
    session_start_hour: int | None = None
    session_end_hour: int | None = None

    # ATR-based exit, an alternative to the plain time-based
    # `holding_period_bars` exit above. False (the default) is the
    # unchanged pre-existing behavior. When True, a stop/target is set
    # from the ATR at entry (entry_price -/+ atr_exit_multiple * ATR) and
    # checked every bar via high/low - the exit reacts to how far price
    # has actually moved, not an arbitrary bar count disconnected from the
    # entry thesis. `holding_period_bars` still applies as a hard cap even
    # in this mode (a stop/target that's never touched must still exit
    # eventually), so it is never a pure either/or.
    use_atr_exit: bool = False
    atr_period: int = 14
    atr_exit_multiple: float = 2.0

    # Genuine execution delay: a signal on bar N is not submitted until bar
    # N + entry_delay_bars, filled at THAT bar's close - not a post-hoc PnL
    # adjustment (see src.research.orchestrator._entry_lag_return, which
    # approximates this after the fact when a strategy has never actually
    # been re-run with a delayed entry). 0 (default) preserves the exact
    # pre-existing same-bar-fill behavior for every strategy/test.
    entry_delay_bars: int = 0

    def __post_init__(self) -> None:
        if self.entry_delay_bars < 0:
            raise ValueError(f"entry_delay_bars must be >= 0, got {self.entry_delay_bars}")
        has_start = self.session_start_hour is not None
        has_end = self.session_end_hour is not None
        if has_start != has_end:
            raise ValueError("session_start_hour and session_end_hour must be set together")
        if has_start:
            for name, value in (
                ("session_start_hour", self.session_start_hour),
                ("session_end_hour", self.session_end_hour),
            ):
                if not 0 <= value <= 23:
                    raise ValueError(f"{name} must be in [0, 23], got {value}")
            if self.session_start_hour == self.session_end_hour:
                raise ValueError(
                    "session_start_hour and session_end_hour must differ "
                    "(use None/None to disable the session filter, not equal hours)"
                )
        if self.use_atr_exit:
            if self.atr_period < 2:
                raise ValueError(f"atr_period must be >= 2, got {self.atr_period}")
            if self.atr_exit_multiple <= 0:
                raise ValueError(f"atr_exit_multiple must be > 0, got {self.atr_exit_multiple}")


class HoldForBarsStrategy(Strategy):
    """Enter per `signal()` when flat and the risk engine approves, hold for
    `holding_period_bars` bars, exit, repeat.
    """

    def __init__(self, config: BenchmarkStrategyConfig) -> None:
        super().__init__(config)
        self._bars_in_position = 0
        self._vol_closes: deque[float] = deque(maxlen=config.vol_lookback_bars + 1)
        self._ohlc_history: deque[dict[str, float]] = deque(maxlen=config.atr_period + 1)
        self._entry_side: OrderSide | None = None
        self._stop_price: float | None = None
        self._target_price: float | None = None
        self._pending_signal: OrderSide | None = None
        self._pending_bars_waited: int = 0
        self._risk_key = str(config.instrument_id)
        # Not part of BenchmarkStrategyConfig (a NautilusTrader msgspec
        # Struct can't hold an arbitrary Python object) - set as a plain
        # attribute post-construction by a caller that wants live/paper
        # fills recorded (Phase 14, see src/execution/session_recorder.py).
        # None (the default) costs nothing and changes no existing
        # strategy's behavior.
        self.session_recorder: SessionRecorder | None = None
        self._risk_engine = RiskEngine(
            RiskConfig(
                risk_per_trade=config.risk_per_trade,
                max_portfolio_risk=config.max_portfolio_risk,
                max_daily_loss=config.max_daily_loss,
                max_drawdown=config.max_drawdown,
                max_concurrent_positions=config.max_concurrent_positions,
                max_leverage=config.max_leverage,
                volatility_target=config.volatility_target,
            )
        )

    def on_start(self) -> None:
        self.subscribe_bars(self.config.bar_type)
        self.log.info(f"Subscribed to bars: {self.config.bar_type}")

    def on_position_closed(self, event: PositionClosed) -> None:
        self._risk_engine.close_position(
            self._risk_key, event.realized_pnl.as_double(), self.clock.utc_now()
        )

    def on_order_filled(self, event: OrderFilled) -> None:
        if self.session_recorder is not None:
            self.session_recorder.on_order_filled(event)

    def on_order_rejected(self, event: OrderRejected) -> None:
        if self.session_recorder is not None:
            self.session_recorder.on_order_rejected(event)

    def _in_session(self, bar: Bar) -> bool:
        if self.config.session_start_hour is None:
            return True
        hour = pd.Timestamp(bar.ts_event, unit="ns", tz="UTC").hour
        start, end = self.config.session_start_hour, self.config.session_end_hour
        if start < end:
            return start <= hour < end
        return hour >= start or hour < end  # wraps midnight

    def on_bar(self, bar: Bar) -> None:
        self.log.info(f"Bar received: {bar}")
        self._vol_closes.append(float(bar.close))
        self._ohlc_history.append(
            {"high": float(bar.high), "low": float(bar.low), "close": float(bar.close)}
        )
        instrument = self.cache.instrument(self.config.instrument_id)
        if instrument is None:
            return
        in_session = self._in_session(bar)

        if not self.portfolio.is_flat(self.config.instrument_id):
            if not in_session:
                # Day-trading session filter: never carry a position outside
                # the configured window, regardless of holding_period_bars.
                self.close_all_positions(self.config.instrument_id)
                self._reset_position_state()
                return
            if self.config.use_atr_exit and self._stop_price is not None:
                if self._atr_stop_or_target_hit(bar):
                    self.close_all_positions(self.config.instrument_id)
                    self._reset_position_state()
                    return
            self._bars_in_position += 1
            if self._bars_in_position >= self.config.holding_period_bars:
                self.close_all_positions(self.config.instrument_id)
                self._reset_position_state()
            return

        if not in_session:
            return

        # Always call signal() - subclasses update their own rolling
        # indicator state as a side effect of this call (e.g. appending to
        # a deque), even on bars where it returns None. Skipping the call
        # while a delayed entry is pending would silently starve that
        # state of bars.
        new_side = self.signal(bar)

        if self._pending_signal is not None:
            self._pending_bars_waited += 1
            if self._pending_bars_waited < self.config.entry_delay_bars:
                return
            side = self._pending_signal
            self._pending_signal = None
            self._pending_bars_waited = 0
        elif new_side is not None:
            if self.config.entry_delay_bars > 0:
                self._pending_signal = new_side
                self._pending_bars_waited = 0
                return
            side = new_side
        else:
            return

        entry_atr: float | None = None
        if self.config.use_atr_exit:
            entry_atr = self._current_atr()
            if entry_atr is None:
                return  # not enough bar history yet for a safe stop/target

        equity = self.portfolio.account(instrument.id.venue).balance_total(
            instrument.quote_currency
        )
        decision = self._risk_engine.evaluate(
            instrument=instrument,
            price=float(bar.close),
            equity=equity.as_double(),
            now=self.clock.utc_now(),
            realized_vol=self._realized_vol(),
        )
        if not decision.approved:
            return

        order = self.order_factory.market(self.config.instrument_id, side, decision.quantity)
        if self.session_recorder is not None:
            self.session_recorder.record_intent(
                order.client_order_id,
                OrderIntent(
                    symbol=str(self.config.instrument_id),
                    side=IntentSide.BUY if side == OrderSide.BUY else IntentSide.SELL,
                    quantity=float(decision.quantity),
                    reference_price=float(bar.close),
                    created_at=self.clock.utc_now(),
                    reason=type(self).__name__,
                ),
            )
        self.submit_order(order)
        self._risk_engine.open_position(self._risk_key, decision.risk_fraction)
        self._bars_in_position = 0
        if entry_atr is not None:
            entry_price = float(bar.close)
            distance = self.config.atr_exit_multiple * entry_atr
            self._entry_side = side
            if side == OrderSide.BUY:
                self._stop_price = entry_price - distance
                self._target_price = entry_price + distance
            else:
                self._stop_price = entry_price + distance
                self._target_price = entry_price - distance

    def _atr_stop_or_target_hit(self, bar: Bar) -> bool:
        assert self._stop_price is not None and self._target_price is not None
        high, low = float(bar.high), float(bar.low)
        if self._entry_side == OrderSide.BUY:
            return low <= self._stop_price or high >= self._target_price
        return high >= self._stop_price or low <= self._target_price

    def _current_atr(self) -> float | None:
        if len(self._ohlc_history) < self.config.atr_period + 1:
            return None
        value = indicators.atr(pd.DataFrame(self._ohlc_history), self.config.atr_period).iloc[-1]
        return float(value) if pd.notna(value) else None

    def _reset_position_state(self) -> None:
        self._bars_in_position = 0
        self._entry_side = None
        self._stop_price = None
        self._target_price = None

    def _realized_vol(self) -> float | None:
        """Simple realized volatility (stdev of per-bar returns) over the
        strategy's own bar history - kept local rather than importing
        src.regimes.indicators to avoid a pandas rolling-window recompute on
        every single bar; this is O(vol_lookback_bars) per call, using a
        fixed-size deque.
        """
        if self._vol_closes.maxlen is None or len(self._vol_closes) < self._vol_closes.maxlen:
            return None
        closes = list(self._vol_closes)
        returns = [
            (closes[i] - closes[i - 1]) / closes[i - 1]
            for i in range(1, len(closes))
            if closes[i - 1] != 0
        ]
        if len(returns) < 2:
            return None
        mean = sum(returns) / len(returns)
        variance = sum((r - mean) ** 2 for r in returns) / (len(returns) - 1)
        return variance**0.5

    @abstractmethod
    def signal(self, bar: Bar) -> OrderSide | None:
        """Return BUY/SELL to enter on this bar, or None to stay flat."""
