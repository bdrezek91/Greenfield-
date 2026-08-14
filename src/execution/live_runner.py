"""Exchange-agnostic live/paper trading loop for exchanges without a
NautilusTrader live adapter - Kraken's counterpart to
src.strategies.base.HoldForBarsStrategy (which only runs inside a
NautilusTrader engine/node), see docs/PROJECT_STATUS.md's exchange
migration entry for why this exists.

Reuses every component already built to be NautilusTrader/exchange-
independent: RiskEngine (src.risk.engine - takes a NautilusTrader
`Instrument` only as a static value object for quantity rounding, not a
live-engine dependency), `momentum_signal` (src.strategies.signals), the
`ExecutionAdapter` Protocol (src.execution.adapter), and `FillTracker`
(src.execution.fill_tracking). Only the "hold for N bars, then exit" exit
timer is reimplemented here (matching `HoldForBarsStrategy`'s semantics
exactly) since that logic lives inside a NautilusTrader `Strategy`
subclass this loop can't reuse directly.

Position state (side/quantity) is tracked locally by this loop, not
reconciled against the exchange's own account/positions endpoint - a known
simplification (see docs/PROJECT_STATUS.md's Known Issues), acceptable for
a first implementation but a real gap for a long-running unattended
session where a manual intervention or a missed fill could desync it from
reality.

Bar delivery and equity are both injected (`bar_source`, `equity_fn`)
rather than hardcoded to Kraken's API - the same testability pattern used
throughout this project (e.g. src/data/kraken_client.py's transport,
src/execution/supervisor.py's sleep_fn/now_fn).
"""

from __future__ import annotations

from collections import deque
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from datetime import datetime

from nautilus_trader.model.enums import OrderSide
from nautilus_trader.model.instruments import Instrument

from src.execution.adapter import ExecutionAdapter
from src.execution.fill_tracking import FillTracker
from src.execution.intent import IntentSide, OrderIntent
from src.risk.engine import RiskEngine
from src.strategies.signals import momentum_signal


@dataclass(frozen=True)
class LiveBar:
    timestamp: datetime
    close: float


@dataclass(frozen=True)
class LiveRunnerConfig:
    symbol: str
    holding_period_bars: int = 24
    momentum_lookback_bars: int = 10
    momentum_threshold: float = 0.01


def _opposite(side: OrderSide) -> OrderSide:
    return OrderSide.SELL if side == OrderSide.BUY else OrderSide.BUY


class LiveRunner:
    def __init__(
        self,
        config: LiveRunnerConfig,
        instrument: Instrument,
        risk_engine: RiskEngine,
        execution_adapter: ExecutionAdapter,
        equity_fn: Callable[[], float],
        fill_tracker: FillTracker | None = None,
    ) -> None:
        self.config = config
        self._instrument = instrument
        self._risk_engine = risk_engine
        self._adapter = execution_adapter
        self._equity_fn = equity_fn
        self.tracker = fill_tracker or FillTracker()

        self._closes: deque[float] = deque(maxlen=config.momentum_lookback_bars + 1)
        self._bars_in_position = 0
        self._current_side: OrderSide | None = None
        self._current_quantity: float = 0.0
        self._current_entry_price: float = 0.0
        self._risk_key = config.symbol

    @property
    def is_flat(self) -> bool:
        return self._current_side is None

    def on_bar(self, bar: LiveBar) -> None:
        self._closes.append(bar.close)

        if self._current_side is not None:
            self._bars_in_position += 1
            if self._bars_in_position >= self.config.holding_period_bars:
                self._close_position(bar)
            return

        side = momentum_signal(
            self._closes, self.config.momentum_lookback_bars, self.config.momentum_threshold
        )
        if side is None:
            return

        decision = self._risk_engine.evaluate(
            instrument=self._instrument,
            price=bar.close,
            equity=self._equity_fn(),
            now=bar.timestamp,
        )
        if not decision.approved:
            return

        self._open_position(side, decision.quantity.as_double(), decision.risk_fraction, bar)

    def run(self, bars: Iterable[LiveBar]) -> None:
        for bar in bars:
            self.on_bar(bar)

    def _open_position(
        self, side: OrderSide, quantity: float, risk_fraction: float, bar: LiveBar
    ) -> None:
        intent = OrderIntent(
            symbol=self.config.symbol,
            side=IntentSide.BUY if side == OrderSide.BUY else IntentSide.SELL,
            quantity=quantity,
            reference_price=bar.close,
            created_at=bar.timestamp,
            reason="live_runner entry",
        )
        fill = self._adapter.submit(intent)
        self.tracker.record(intent, fill)
        if fill.rejected:
            return

        self._current_side = side
        self._current_quantity = fill.filled_quantity
        self._current_entry_price = fill.filled_price
        self._bars_in_position = 0
        self._risk_engine.open_position(self._risk_key, risk_fraction)

    def _close_position(self, bar: LiveBar) -> None:
        assert self._current_side is not None
        exit_side = _opposite(self._current_side)
        intent = OrderIntent(
            symbol=self.config.symbol,
            side=IntentSide.BUY if exit_side == OrderSide.BUY else IntentSide.SELL,
            quantity=self._current_quantity,
            reference_price=bar.close,
            created_at=bar.timestamp,
            reason="live_runner exit",
        )
        fill = self._adapter.submit(intent)
        self.tracker.record(intent, fill)
        if fill.rejected:
            # Leave the position "open" from this loop's point of view -
            # retrying the exit next bar is safer than silently forgetting
            # about a position the exchange still has open.
            return

        # Gross realized PnL only (entry vs. exit fill price x quantity,
        # signed by direction) - fees/commissions aren't deducted here,
        # unlike the backtest engine's NautilusTrader-computed realized_pnl
        # (src/backtesting/reports.py). A known simplification: the risk
        # engine's max_daily_loss/max_drawdown tracking on this path is
        # therefore slightly optimistic relative to actual account equity.
        direction_sign = 1.0 if self._current_side == OrderSide.BUY else -1.0
        realized_pnl = direction_sign * (fill.filled_price - self._current_entry_price) * (
            self._current_quantity
        )
        self._risk_engine.close_position(self._risk_key, realized_pnl, bar.timestamp)
        self._current_side = None
        self._current_quantity = 0.0
        self._current_entry_price = 0.0
        self._bars_in_position = 0
