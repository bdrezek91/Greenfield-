"""ExecutionAssumptions must build usable, reproducible fee/fill models."""

import pandas as pd
import pytest
from nautilus_trader.backtest.models import FeeModel, FillModel

from src.backtesting.costs import ExecutionAssumptions, apply_spread_costs


def test_fee_model_is_maker_taker_based() -> None:
    model = ExecutionAssumptions().fee_model()
    assert isinstance(model, FeeModel)


def test_fill_model_uses_configured_slippage_and_seed() -> None:
    assumptions = ExecutionAssumptions(prob_slippage=0.3, random_seed=7)
    model = assumptions.fill_model()
    assert isinstance(model, FillModel)


def test_default_assumptions_are_reproducible_by_default() -> None:
    assert ExecutionAssumptions().random_seed is not None


def test_adverse_slippage_multiplier_changes_actual_fill_model_probability() -> None:
    base = ExecutionAssumptions(prob_slippage=0.2, slippage_multiplier=1.0)
    adverse = ExecutionAssumptions(prob_slippage=0.2, slippage_multiplier=2.0)
    assert base.fill_model().prob_slippage == 0.2
    assert adverse.fill_model().prob_slippage == 0.4


def test_spread_cost_charges_both_legs_only_for_closed_trade() -> None:
    trades = pd.DataFrame(
        [
            {
                "quantity": 2.0,
                "entry_price": 100.0,
                "exit_price": 110.0,
                "fees": 1.0,
                "is_mark_to_market": False,
            },
            {
                "quantity": 2.0,
                "entry_price": 100.0,
                "exit_price": 110.0,
                "fees": 1.0,
                "is_mark_to_market": True,
            },
        ]
    )
    result = apply_spread_costs(trades, spread_bps=10.0)
    assert result.loc[0, "fees"] == pytest.approx(1.21)
    assert result.loc[1, "fees"] == pytest.approx(1.10)
