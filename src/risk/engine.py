"""Risk engine: the gatekeeper between a strategy's signal and an actual order.

Per docs/PHASE_0_ARCHITECTURE_RESEARCH.md section 29: the strategy generates
a signal; the risk engine decides whether entry is allowed and how large a
position may be. Deliberately decoupled from NautilusTrader - generic
(price, equity, timestamp) inputs, with an `Instrument` used only at the
very end to round the computed notional into a valid `Quantity` - so it's
testable without a running backtest engine, the same adapter pattern used
elsewhere in this project (src/backtesting/funding.py, reports.py).

This engine is STATEFUL: it tracks each open position's committed risk
fraction and today's realized PnL itself, via `open_position`/
`close_position`, because NautilusTrader's own reports don't expose "how
much risk did we target for this position" - only the caller (the
strategy) knows that at entry time.

Scope note: `max_concurrent_positions` and `max_portfolio_risk` track
positions this SAME RiskEngine instance opened (keyed by a caller-supplied
string, typically the instrument ID) - there is no cross-strategy or
cross-instrument portfolio view yet. True multi-instrument, simultaneously-
running strategies sharing one risk budget are a later-phase concern; see
docs/PROJECT_STATUS.md.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime

from nautilus_trader.model.instruments import Instrument
from nautilus_trader.model.objects import Quantity


@dataclass(frozen=True)
class RiskConfig:
    risk_per_trade: float = 0.01
    """Fraction of equity committed per trade under normal conditions."""

    max_portfolio_risk: float = 0.05
    """Sum of committed risk fractions across all positions this engine has open."""

    max_daily_loss: float = 0.03
    """Fraction of equity; breached -> no new entries for the rest of that UTC day."""

    max_drawdown: float = 0.25
    """Fraction below peak equity; breached -> no new entries until equity recovers."""

    max_concurrent_positions: int = 1

    max_leverage: float = 3.0
    """Cap on notional / equity for any single position."""

    volatility_target: float | None = None
    """If set, risk is scaled by volatility_target / realized_vol - both MUST
    be on the same period basis as each other (e.g. both per-bar), or this
    silently produces a meaningless size, the same class of scale-mismatch
    bug documented in src/analytics/robustness.py. None (default) disables
    vol targeting and uses `risk_per_trade` directly.
    """


@dataclass(frozen=True)
class RiskDecision:
    approved: bool
    quantity: Quantity
    risk_fraction: float
    reason: str


@dataclass
class _OpenPosition:
    risk_fraction: float


class RiskEngine:
    def __init__(self, config: RiskConfig) -> None:
        self.config = config
        self._open_positions: dict[str, _OpenPosition] = {}
        self._peak_equity: float = 0.0
        self._daily_pnl: float = 0.0
        self._current_day: date | None = None

    def _roll_day(self, now: datetime) -> bool:
        """Roll the daily ledger forward only; return False for stale input.

        Exchange events can arrive out of order.  Moving the ledger backwards
        would erase the current UTC day's realised loss and reopen the entry
        gate.  Stale closes are still charged to the current ledger by the
        caller, while stale entry evaluations fail closed.
        """
        today = now.date()
        if self._current_day is None or today > self._current_day:
            self._current_day = today
            self._daily_pnl = 0.0
            return True
        return today == self._current_day

    def evaluate(
        self,
        *,
        instrument: Instrument,
        price: float,
        equity: float,
        now: datetime,
        realized_vol: float | None = None,
    ) -> RiskDecision:
        """Decide whether a new entry is allowed and, if so, how large."""
        if not self._roll_day(now):
            return RiskDecision(
                False,
                instrument.make_qty(0),
                0.0,
                "out-of-order timestamp",
            )
        self._peak_equity = max(self._peak_equity, equity)
        zero = instrument.make_qty(0)

        if len(self._open_positions) >= self.config.max_concurrent_positions:
            return RiskDecision(False, zero, 0.0, "max_concurrent_positions reached")

        if equity > 0 and self._daily_pnl <= -self.config.max_daily_loss * equity:
            return RiskDecision(False, zero, 0.0, "max_daily_loss breached")

        if self._peak_equity > 0:
            drawdown = (equity - self._peak_equity) / self._peak_equity
            if drawdown <= -self.config.max_drawdown:
                return RiskDecision(False, zero, 0.0, "max_drawdown breached")

        risk_fraction = self.config.risk_per_trade
        if self.config.volatility_target is not None and realized_vol and realized_vol > 0:
            vol_scale = self.config.volatility_target / realized_vol
            risk_fraction = vol_scale * self.config.risk_per_trade

        open_risk_sum = sum(p.risk_fraction for p in self._open_positions.values())
        available_risk = self.config.max_portfolio_risk - open_risk_sum
        if available_risk <= 0:
            return RiskDecision(False, zero, 0.0, "max_portfolio_risk reached")
        risk_fraction = max(0.0, min(risk_fraction, available_risk))

        if price <= 0 or risk_fraction <= 0:
            return RiskDecision(False, zero, 0.0, "no valid risk budget")

        notional = equity * risk_fraction
        max_notional = equity * self.config.max_leverage
        notional = min(notional, max_notional)

        quantity = instrument.make_qty(notional / price, round_down=True)
        if quantity.as_double() <= 0:
            return RiskDecision(False, quantity, 0.0, "computed size rounds to zero")

        return RiskDecision(True, quantity, risk_fraction, "approved")

    def open_position(self, key: str, risk_fraction: float) -> None:
        self._open_positions[key] = _OpenPosition(risk_fraction)

    def close_position(self, key: str, realized_pnl: float, now: datetime) -> None:
        """`now` must be passed here too (not just `evaluate`) - a loss
        recorded before the next `evaluate` call would otherwise be wiped
        out by `_roll_day` treating the still-uninitialized day as "new."
        """
        self._roll_day(now)
        self._open_positions.pop(key, None)
        self._daily_pnl += realized_pnl

    @property
    def open_position_count(self) -> int:
        return len(self._open_positions)
