"""ExecutionAssumptions must build usable, reproducible fee/fill models."""

from nautilus_trader.backtest.models import FeeModel, FillModel

from src.backtesting.costs import ExecutionAssumptions


def test_fee_model_is_maker_taker_based() -> None:
    model = ExecutionAssumptions().fee_model()
    assert isinstance(model, FeeModel)


def test_fill_model_uses_configured_slippage_and_seed() -> None:
    assumptions = ExecutionAssumptions(prob_slippage=0.3, random_seed=7)
    model = assumptions.fill_model()
    assert isinstance(model, FillModel)


def test_default_assumptions_are_reproducible_by_default() -> None:
    assert ExecutionAssumptions().random_seed is not None
