from __future__ import annotations

import pytest

from src.data.raw_venue_soak import (
    SUPPORTED_RAW_SOAK_VENUES,
    raw_venue_soak_contract,
)


def test_every_phase3_venue_has_an_isolated_complete_contract() -> None:
    assert SUPPORTED_RAW_SOAK_VENUES == ("okx", "binance", "coinbase", "deribit")
    namespaces = set()
    services = set()
    for venue in SUPPORTED_RAW_SOAK_VENUES:
        contract = raw_venue_soak_contract(venue)
        assert contract.venue == venue
        assert contract.compose_profile == venue
        assert contract.health_namespace.startswith(f"{venue}-")
        assert contract.collector_ids
        assert len(contract.collector_ids) == len(set(contract.collector_ids))
        assert len(contract.collector_ids) == len(contract.compose_services)
        assert namespaces.isdisjoint({contract.health_namespace})
        assert services.isdisjoint(contract.compose_services)
        namespaces.add(contract.health_namespace)
        services.update(contract.compose_services)


def test_unknown_phase3_venue_fails_closed() -> None:
    with pytest.raises(ValueError, match="unsupported raw soak venue"):
        raw_venue_soak_contract("kraken")
