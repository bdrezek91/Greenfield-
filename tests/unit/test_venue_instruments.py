from __future__ import annotations

from datetime import UTC, datetime

import pytest

from src.data.instruments import InstrumentRegistry, ProductType, VenueInstrument


def _perpetual(exchange: str, market: str, symbol: str) -> VenueInstrument:
    return VenueInstrument(
        exchange=exchange,
        market_type=market,
        venue_symbol=symbol,
        base_asset="BTC",
        quote_asset="USDT",
        settlement_asset="USDT",
        product_type=ProductType.PERPETUAL,
    )


def test_registry_maps_different_symbols_to_one_canonical_instrument() -> None:
    bybit = _perpetual("bybit", "linear", "BTCUSDT")
    okx = _perpetual("okx", "swap", "BTC-USDT-SWAP")
    registry = InstrumentRegistry((bybit, okx))

    assert bybit.canonical_id == "BTC-USDT:PERP:USDT"
    assert registry.resolve("OKX", "SWAP", "BTC-USDT-SWAP") == okx
    assert registry.venues_for(bybit.canonical_id) == (bybit, okx)


def test_same_symbol_can_exist_in_separate_product_namespaces() -> None:
    perpetual = _perpetual("binance", "linear", "BTCUSDT")
    spot = VenueInstrument(
        exchange="binance",
        market_type="spot",
        venue_symbol="BTCUSDT",
        base_asset="BTC",
        quote_asset="USDT",
        product_type=ProductType.SPOT,
    )
    registry = InstrumentRegistry((perpetual, spot))

    assert registry.resolve("binance", "spot", "BTCUSDT") == spot
    assert registry.resolve("binance", "linear", "BTCUSDT") == perpetual
    assert spot.canonical_id != perpetual.canonical_id


def test_option_identity_requires_expiry_strike_and_right() -> None:
    option = VenueInstrument(
        exchange="deribit",
        market_type="option",
        venue_symbol="BTC-25DEC26-100000-C",
        base_asset="BTC",
        quote_asset="USD",
        settlement_asset="BTC",
        product_type=ProductType.OPTION,
        expiry_utc=datetime(2026, 12, 25, 8, tzinfo=UTC),
        option_strike="100000",
        option_right="call",
    )

    assert option.canonical_id == "BTC-USD:OPT:20261225:100000:C"
    with pytest.raises(ValueError, match="require strike"):
        VenueInstrument(
            exchange="deribit",
            market_type="option",
            venue_symbol="bad",
            base_asset="BTC",
            quote_asset="USD",
            product_type=ProductType.OPTION,
            expiry_utc=datetime(2026, 12, 25, tzinfo=UTC),
        )


def test_registry_rejects_ambiguous_or_unknown_mapping() -> None:
    instrument = _perpetual("bybit", "linear", "BTCUSDT")
    registry = InstrumentRegistry((instrument,))
    conflicting = VenueInstrument(
        exchange="bybit",
        market_type="linear",
        venue_symbol="BTCUSDT",
        base_asset="BTC",
        quote_asset="USD",
        product_type=ProductType.PERPETUAL,
    )
    with pytest.raises(ValueError, match="ambiguous"):
        registry.register(conflicting)
    with pytest.raises(KeyError, match="unknown venue"):
        registry.resolve("okx", "swap", "BTC-USDT-SWAP")
