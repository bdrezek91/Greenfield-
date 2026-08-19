"""Fee and fill (slippage) model configuration for the backtest venue.

Every value here is part of an experiment's recorded assumptions (see
docs/RESEARCH_METHODOLOGY.md) - a backtest is never run with silent defaults
that assume perfect execution at the close price.

`fee_multiplier`/`slippage_multiplier`/`entry_delay_bars` exist so that
configs/research_protocol.yaml's `costs.base`/`costs.adverse`/`costs.severe`
scenarios can produce genuinely different, worse-with-scenario execution
inside the real NautilusTrader engine - not just a post-hoc report
adjustment. Previously these three fields were parsed out of the protocol
into `ResearchProtocolConfig` but never consumed anywhere in the execution
path (`ExecutionAssumptions` had no fields for them at all); only
`funding_multiplier` was ever wired, and only for the `adverse` scenario.
See docs/AUTONOMOUS_RESEARCH_AUDIT.md and the fix logged in
docs/PROJECT_STATUS.md for the audit trail of that gap.
"""

from __future__ import annotations

from dataclasses import dataclass

from nautilus_trader.backtest.models import FeeModel, FillModel, MakerTakerFeeModel
from nautilus_trader.model.objects import Money


class _ScaledFeeModel(FeeModel):
    """Wraps `MakerTakerFeeModel` (fees read from the instrument's own
    maker_fee/taker_fee) and multiplies the resulting commission by
    `multiplier` - so `costs.adverse.fee_multiplier`/`costs.severe.
    fee_multiplier` in research_protocol.yaml actually change what NautilusTrader
    charges per fill, instead of being parsed and then silently unused.
    """

    def __init__(self, multiplier: float) -> None:
        super().__init__()
        self._inner = MakerTakerFeeModel()
        self._multiplier = multiplier

    def get_commission(self, order, fill_qty, fill_px, instrument):  # noqa: ANN001
        base = self._inner.get_commission(order, fill_qty, fill_px, instrument)
        return Money(base.as_double() * self._multiplier, base.currency)


@dataclass(frozen=True)
class ExecutionAssumptions:
    """Recorded, not-silently-defaulted execution cost assumptions.

    `fee_multiplier`/`slippage_multiplier` scale `base`'s cost linearly for
    `adverse`/`severe` (per research_protocol.yaml). `entry_delay_bars` is
    consumed by `src.strategies.base.HoldForBarsStrategy`, not the engine
    itself - `src.backtesting.runner.run_backtest_window` injects it into
    every strategy config that declares the field (all of them, via
    `BenchmarkStrategyConfig`).
    """

    fee_multiplier: float = 1.0
    slippage_multiplier: float = 1.0
    entry_delay_bars: int = 0

    prob_slippage: float = 0.2
    """Base probability (at slippage_multiplier=1.0) that a fill slips by
    one tick, applied to every order. Scaled by `slippage_multiplier` and
    capped at 1.0 in `fill_model()` below."""

    random_seed: int | None = 42
    """Fixed by default so backtests are reproducible; set None for Monte Carlo runs."""

    def __post_init__(self) -> None:
        if self.fee_multiplier <= 0:
            raise ValueError("fee_multiplier must be positive")
        if self.slippage_multiplier <= 0:
            raise ValueError("slippage_multiplier must be positive")
        if self.entry_delay_bars < 0:
            raise ValueError("entry_delay_bars must be non-negative")
        if not 0 <= self.prob_slippage <= 1:
            raise ValueError("prob_slippage must be in [0, 1]")

    def fee_model(self) -> FeeModel:
        return _ScaledFeeModel(self.fee_multiplier)

    def fill_model(self) -> FillModel:
        scaled_prob_slippage = min(1.0, self.prob_slippage * self.slippage_multiplier)
        return FillModel(
            prob_fill_on_limit=1.0,
            prob_fill_on_stop=1.0,
            prob_slippage=scaled_prob_slippage,
            random_seed=self.random_seed,
        )
