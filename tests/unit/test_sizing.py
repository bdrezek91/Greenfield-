"""Fixed-fraction sizing must convert equity fraction into a valid, rounded-down Quantity."""

from __future__ import annotations

import pytest
from nautilus_trader.model.currencies import USDT
from nautilus_trader.model.objects import Money

from src.backtesting.instruments import build_crypto_perpetual, load_instrument_specs
from src.strategies.sizing import position_size


@pytest.fixture
def instrument():
    specs = load_instrument_specs()
    return build_crypto_perpetual("BTCUSDT", specs)


def test_position_size_uses_fraction_of_equity(instrument) -> None:
    equity = Money(100_000, USDT)
    qty = position_size(equity, price=50_000.0, fraction=0.1, instrument=instrument)
    # 10% of 100,000 = 10,000 notional / 50,000 price = 0.2 units.
    assert qty.as_double() == pytest.approx(0.2, abs=1e-9)


def test_position_size_rounds_down_to_size_increment(instrument) -> None:
    equity = Money(100_000, USDT)
    # Notional / price = 0.19999999... - must round DOWN, never up past the target risk.
    qty = position_size(equity, price=33_333.0, fraction=0.1, instrument=instrument)
    assert qty.as_double() <= 10_000 / 33_333.0


def test_position_size_zero_for_non_positive_price() -> None:
    equity = Money(100_000, USDT)
    specs = load_instrument_specs()
    instrument = build_crypto_perpetual("BTCUSDT", specs)
    assert position_size(equity, price=0.0, fraction=0.1, instrument=instrument).as_double() == 0.0


def test_position_size_zero_for_non_positive_fraction(instrument) -> None:
    equity = Money(100_000, USDT)
    qty = position_size(equity, price=100.0, fraction=0.0, instrument=instrument)
    assert qty.as_double() == 0.0
