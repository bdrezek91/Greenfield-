"""Fee and fill (slippage) model configuration for the backtest venue.

Every value here is part of an experiment's recorded assumptions (see
docs/RESEARCH_METHODOLOGY.md) - a backtest is never run with silent defaults
that assume perfect execution at the close price.
"""

from __future__ import annotations

from dataclasses import dataclass

from nautilus_trader.backtest.models import FeeModel, FillModel, MakerTakerFeeModel


@dataclass(frozen=True)
class ExecutionAssumptions:
    """Recorded, not-silently-defaulted execution cost assumptions."""

    prob_slippage: float = 0.2
    """Probability that a fill slips by one tick, applied to every order."""

    random_seed: int | None = 42
    """Fixed by default so backtests are reproducible; set None for Monte Carlo runs."""

    def fee_model(self) -> FeeModel:
        """Maker/taker fees are read from each instrument's `maker_fee`/`taker_fee`
        (see src.backtesting.instruments) rather than hardcoded here.
        """
        return MakerTakerFeeModel()

    def fill_model(self) -> FillModel:
        return FillModel(
            prob_fill_on_limit=1.0,
            prob_fill_on_stop=1.0,
            prob_slippage=self.prob_slippage,
            random_seed=self.random_seed,
        )
