"""Canonical deployment identity for each Phase 3 raw venue soak."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class RawVenueSoakContract:
    venue: str
    compose_profile: str
    market_type: str
    health_namespace: str
    collector_ids: tuple[str, ...]
    compose_services: tuple[str, ...]
    venue_symbols: tuple[str, ...]
    required_channels: tuple[str, ...] = ("orderbook", "trades", "ticker")


_CONTRACTS = {
    "okx": RawVenueSoakContract(
        venue="okx",
        compose_profile="okx",
        market_type="swap",
        health_namespace="okx-swap",
        collector_ids=("btc-usdt-swap", "eth-usdt-swap", "sol-usdt-swap"),
        compose_services=("raw-okx-btc", "raw-okx-eth", "raw-okx-sol"),
        venue_symbols=("BTC-USDT-SWAP", "ETH-USDT-SWAP", "SOL-USDT-SWAP"),
    ),
    "binance": RawVenueSoakContract(
        venue="binance",
        compose_profile="binance",
        market_type="linear",
        health_namespace="binance-linear",
        collector_ids=("btcusdt", "ethusdt", "solusdt"),
        compose_services=("raw-binance-btc", "raw-binance-eth", "raw-binance-sol"),
        venue_symbols=("BTCUSDT", "ETHUSDT", "SOLUSDT"),
    ),
    "coinbase": RawVenueSoakContract(
        venue="coinbase",
        compose_profile="coinbase",
        market_type="spot",
        health_namespace="coinbase-spot",
        collector_ids=("btc-usd", "eth-usd", "sol-usd"),
        compose_services=("raw-coinbase-btc", "raw-coinbase-eth", "raw-coinbase-sol"),
        venue_symbols=("BTC-USD", "ETH-USD", "SOL-USD"),
    ),
    "deribit": RawVenueSoakContract(
        venue="deribit",
        compose_profile="deribit",
        market_type="future",
        health_namespace="deribit-future",
        collector_ids=("btc-perpetual", "eth-perpetual"),
        compose_services=("raw-deribit-btc", "raw-deribit-eth"),
        venue_symbols=("BTC-PERPETUAL", "ETH-PERPETUAL"),
    ),
}

SUPPORTED_RAW_SOAK_VENUES = tuple(_CONTRACTS)


def raw_venue_soak_contract(venue: str) -> RawVenueSoakContract:
    normalized = venue.strip().lower()
    try:
        return _CONTRACTS[normalized]
    except KeyError as exc:
        supported = ", ".join(SUPPORTED_RAW_SOAK_VENUES)
        raise ValueError(
            f"unsupported raw soak venue {venue!r}; expected one of {supported}"
        ) from exc
