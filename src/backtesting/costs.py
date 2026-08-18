"""Fee and fill (slippage) model configuration for the backtest venue.

Every value here is part of an experiment's recorded assumptions (see
docs/RESEARCH_METHODOLOGY.md) - a backtest is never run with silent defaults
that assume perfect execution at the close price.
"""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd
from nautilus_trader.backtest.models import FeeModel, FillModel, MakerTakerFeeModel
from nautilus_trader.model.objects import Money


class ScaledMakerTakerFeeModel(FeeModel):
    """Apply a scenario multiplier to the instrument's real maker/taker fee."""

    def __init__(self, multiplier: float) -> None:
        self.multiplier = multiplier
        self._base = MakerTakerFeeModel()

    def get_commission(self, order, fill_qty, fill_px, instrument) -> Money:  # noqa: ANN001
        commission = self._base.get_commission(order, fill_qty, fill_px, instrument)
        return Money(commission.as_double() * self.multiplier, commission.currency)


@dataclass(frozen=True)
class ExecutionAssumptions:
    """Recorded, not-silently-defaulted execution cost assumptions."""

    prob_slippage: float = 0.2
    """Probability that a fill slips by one tick, applied to every order."""

    random_seed: int | None = 42
    """Fixed by default so backtests are reproducible; set None for Monte Carlo runs."""

    fee_multiplier: float = 1.0
    slippage_multiplier: float = 1.0
    spread_bps: float = 2.0
    entry_delay_bars: int = 1
    missed_trade_probability: float = 0.0

    def __post_init__(self) -> None:
        if self.fee_multiplier <= 0 or self.slippage_multiplier <= 0:
            raise ValueError("cost multipliers must be positive")
        if self.spread_bps < 0:
            raise ValueError("spread_bps must be non-negative")
        if self.entry_delay_bars < 0:
            raise ValueError("entry_delay_bars must be non-negative")
        if not 0.0 <= self.missed_trade_probability <= 1.0:
            raise ValueError("missed_trade_probability must be in [0, 1]")

    def fee_model(self) -> FeeModel:
        """Maker/taker fees are read from each instrument's `maker_fee`/`taker_fee`
        (see src.backtesting.instruments) rather than hardcoded here.
        """
        return ScaledMakerTakerFeeModel(self.fee_multiplier)

    def fill_model(self) -> FillModel:
        return FillModel(
            prob_fill_on_limit=1.0,
            prob_slippage=min(1.0, self.prob_slippage * self.slippage_multiplier),
            random_seed=self.random_seed,
        )


def apply_spread_costs(trades: pd.DataFrame, spread_bps: float) -> pd.DataFrame:
    """Charge half-spread on each executed entry/exit leg.

    A still-open MTM row has no real exit and therefore pays only its entry
    leg. The cost is added to the existing fee column so final PnL and MTM
    equity both consume it.
    """
    result = trades.copy()
    if result.empty or spread_bps == 0:
        return result
    half_spread = spread_bps / 20_000.0
    entry_cost = result["quantity"].abs() * result["entry_price"] * half_spread
    closed = ~result.get("is_mark_to_market", pd.Series(False, index=result.index)).astype(bool)
    exit_cost = result["quantity"].abs() * result["exit_price"] * half_spread * closed
    result["fees"] = result.get("fees", 0.0) + entry_cost + exit_cost
    return result
