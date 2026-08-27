"""HyperliquidInfoClient must build the right request body per method,
unwrap responses, and reject an unexpected shape - the Hyperliquid
counterpart to test_okx_derivatives_client.py."""

from __future__ import annotations

import pytest

from src.data.hyperliquid_client import HyperliquidInfoClient


class FakeFetcher:
    def __init__(self, response: object) -> None:
        self.response = response
        self.last_body: dict | None = None

    def __call__(self, body: dict) -> object:
        self.last_body = body
        return self.response


def test_get_meta_and_asset_ctxs_returns_universe_and_ctxs() -> None:
    universe = [{"name": "BTC"}, {"name": "ETH"}]
    ctxs = [{"funding": "0.0000125"}, {"funding": "0.0000200"}]
    fetcher = FakeFetcher([{"universe": universe}, ctxs])
    client = HyperliquidInfoClient(fetcher=fetcher)

    result_universe, result_ctxs = client.get_meta_and_asset_ctxs()

    assert result_universe == universe
    assert result_ctxs == ctxs
    assert fetcher.last_body == {"type": "metaAndAssetCtxs"}


def test_get_meta_and_asset_ctxs_rejects_mismatched_lengths() -> None:
    fetcher = FakeFetcher([{"universe": [{"name": "BTC"}, {"name": "ETH"}]}, [{"funding": "0"}]])
    client = HyperliquidInfoClient(fetcher=fetcher)
    with pytest.raises(RuntimeError, match="length mismatch"):
        client.get_meta_and_asset_ctxs()


def test_get_meta_and_asset_ctxs_rejects_unexpected_shape() -> None:
    client = HyperliquidInfoClient(fetcher=FakeFetcher({"not": "a list"}))
    with pytest.raises(RuntimeError, match="unexpected metaAndAssetCtxs"):
        client.get_meta_and_asset_ctxs()


def test_get_funding_history_builds_body_with_optional_end_time() -> None:
    fetcher = FakeFetcher([{"coin": "BTC", "fundingRate": "0.0000125", "time": 1}])
    client = HyperliquidInfoClient(fetcher=fetcher)

    rows = client.get_funding_history("BTC", start_time_ms=1000)

    assert rows == fetcher.response
    assert fetcher.last_body == {"type": "fundingHistory", "coin": "BTC", "startTime": 1000}

    client.get_funding_history("BTC", start_time_ms=1000, end_time_ms=2000)
    assert fetcher.last_body == {
        "type": "fundingHistory",
        "coin": "BTC",
        "startTime": 1000,
        "endTime": 2000,
    }


def test_get_predicted_fundings_returns_all_coins() -> None:
    response = [["BTC", [["HlPerp", {"fundingRate": "0.0000125"}]]]]
    fetcher = FakeFetcher(response)
    client = HyperliquidInfoClient(fetcher=fetcher)

    result = client.get_predicted_fundings()

    assert result == response
    assert fetcher.last_body == {"type": "predictedFundings"}


def test_get_l2_book_builds_body_and_requires_levels() -> None:
    response = {"coin": "BTC", "time": 1, "levels": [[], []]}
    fetcher = FakeFetcher(response)
    client = HyperliquidInfoClient(fetcher=fetcher)

    result = client.get_l2_book("BTC")

    assert result == response
    assert fetcher.last_body == {"type": "l2Book", "coin": "BTC"}

    bad_client = HyperliquidInfoClient(fetcher=FakeFetcher({"coin": "BTC"}))
    with pytest.raises(RuntimeError, match="unexpected l2Book"):
        bad_client.get_l2_book("BTC")
