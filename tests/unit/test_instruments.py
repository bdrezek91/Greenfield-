"""Instrument specs must load and build valid NautilusTrader CryptoPerpetual instruments."""

import pytest

from src.backtesting.instruments import (
    build_crypto_perpetual,
    instrument_id_for,
    load_instrument_specs,
)


def test_load_instrument_specs() -> None:
    specs = load_instrument_specs()
    assert specs.quote_currency.code == "USD"
    assert specs.maker_fee < specs.taker_fee
    assert "BTCUSD" in specs.base_currencies


def test_instrument_id_format() -> None:
    iid = instrument_id_for("BTCUSD")
    assert str(iid) == "BTCUSD-PERP.KRAKEN"


def test_build_crypto_perpetual_matches_specs() -> None:
    specs = load_instrument_specs()
    instrument = build_crypto_perpetual("BTCUSD", specs)

    assert str(instrument.id) == "BTCUSD-PERP.KRAKEN"
    assert instrument.quote_currency.code == "USD"
    assert instrument.base_currency.code == "BTC"
    assert float(instrument.maker_fee) == float(specs.maker_fee)
    assert float(instrument.taker_fee) == float(specs.taker_fee)


def test_build_crypto_perpetual_unknown_symbol_raises() -> None:
    specs = load_instrument_specs()
    with pytest.raises(ValueError, match="NOPEUSD"):
        build_crypto_perpetual("NOPEUSD", specs)
