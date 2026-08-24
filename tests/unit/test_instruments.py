"""Instrument specs must load and build valid NautilusTrader CryptoPerpetual instruments."""

import pytest

from src.backtesting.instruments import (
    build_crypto_perpetual,
    instrument_id_for,
    load_instrument_specs,
)


def test_load_instrument_specs() -> None:
    specs = load_instrument_specs()
    assert specs.quote_currency.code == "USDT"
    assert specs.maker_fee < specs.taker_fee
    assert "BTCUSDT" in specs.base_currencies


def test_instrument_id_format() -> None:
    iid = instrument_id_for("BTCUSDT")
    assert str(iid) == "BTCUSDT-PERP.BYBIT"


def test_build_crypto_perpetual_matches_specs() -> None:
    specs = load_instrument_specs()
    instrument = build_crypto_perpetual("BTCUSDT", specs)

    assert str(instrument.id) == "BTCUSDT-PERP.BYBIT"
    assert instrument.quote_currency.code == "USDT"
    assert instrument.base_currency.code == "BTC"
    assert float(instrument.maker_fee) == float(specs.maker_fee)
    assert float(instrument.taker_fee) == float(specs.taker_fee)
    assert str(instrument.price_increment) == "0.1"
    assert str(instrument.size_increment) == "0.001"
    eth = build_crypto_perpetual("ETHUSDT", specs)
    assert str(eth.size_increment) == "0.01"


def test_build_crypto_perpetual_unknown_symbol_raises() -> None:
    specs = load_instrument_specs()
    with pytest.raises(ValueError, match="NOPEUSDT"):
        build_crypto_perpetual("NOPEUSDT", specs)
