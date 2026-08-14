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

from nautilus_trader.model.data import Bar, BarType
from nautilus_trader.model.enums import OrderSide
from nautilus_trader.model.events import PositionClosed
from nautilus_trader.model.identifiers import InstrumentId
from nautilus_trader.trading.strategy import Strategy, StrategyConfig

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


class HoldForBarsStrategy(Strategy):
    """Enter per `signal()` when flat and the risk engine approves, hold for
    `holding_period_bars` bars, exit, repeat.
    """

    def __init__(self, config: BenchmarkStrategyConfig) -> None:
        super().__init__(config)
        self._bars_in_position = 0
        self._vol_closes: deque[float] = deque(maxlen=config.vol_lookback_bars + 1)
        self._risk_key = str(config.instrument_id)
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

    def on_position_closed(self, event: PositionClosed) -> None:
        self._risk_engine.close_position(
            self._risk_key, event.realized_pnl.as_double(), self.clock.utc_now()
        )

    def on_bar(self, bar: Bar) -> None:
        self._vol_closes.append(float(bar.close))
        instrument = self.cache.instrument(self.config.instrument_id)
        if instrument is None:
            return

        if not self.portfolio.is_flat(self.config.instrument_id):
            self._bars_in_position += 1
            if self._bars_in_position >= self.config.holding_period_bars:
                self.close_all_positions(self.config.instrument_id)
                self._bars_in_position = 0
            return

        side = self.signal(bar)
        if side is None:
            return

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

        self.submit_order(
            self.order_factory.market(self.config.instrument_id, side, decision.quantity)
        )
        self._risk_engine.open_position(self._risk_key, decision.risk_fraction)
        self._bars_in_position = 0

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
