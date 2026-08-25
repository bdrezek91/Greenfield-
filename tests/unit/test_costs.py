"""ExecutionAssumptions must build usable, reproducible fee/fill models."""

from nautilus_trader.backtest.models import FeeModel, FillModel

from src.backtesting.costs import ExecutionAssumptions
from src.backtesting.runner import execution_metadata


def test_fee_model_is_maker_taker_based() -> None:
    model = ExecutionAssumptions().fee_model()
    assert isinstance(model, FeeModel)


def test_fill_model_uses_configured_slippage_and_seed() -> None:
    assumptions = ExecutionAssumptions(prob_slippage=0.3, random_seed=7)
    model = assumptions.fill_model()
    assert isinstance(model, FillModel)


def test_default_assumptions_are_reproducible_by_default() -> None:
    assert ExecutionAssumptions().random_seed is not None


def test_experiment_metadata_records_actual_execution_assumptions() -> None:
    assumptions = ExecutionAssumptions(
        fee_multiplier=1.5,
        slippage_multiplier=2.0,
        entry_delay_bars=3,
        prob_slippage=0.3,
        random_seed=17,
    )
    fees, slippage = execution_metadata(assumptions)
    assert fees["fee_multiplier"] == 1.5
    assert slippage == {
        "prob_slippage": 0.3,
        "slippage_multiplier": 2.0,
        "effective_prob_slippage": 0.6,
        "random_seed": 17,
        "entry_delay_bars": 3,
    }
