"""DeribitMarketSummaryClient must build correct query params, pass rows
through untouched, and reject invalid currency/kind - the Deribit
counterpart to test_binance_derivatives_client.py/test_okx_derivatives_client.py.
"""

from __future__ import annotations

import pytest

from src.data.deribit_market_summary_client import DeribitMarketSummaryClient


class FakeFetcher:
    def __init__(self, response: list[dict]) -> None:
        self.response = response
        self.last_path: str | None = None
        self.last_params: dict | None = None

    def __call__(self, path: str, params: dict) -> list[dict]:
        self.last_path = path
        self.last_params = params
        return self.response


def test_get_book_summary_returns_rows_and_builds_params() -> None:
    fetcher = FakeFetcher([{"instrument_name": "BTC-PERPETUAL", "mark_price": 1.0}])
    client = DeribitMarketSummaryClient(fetcher=fetcher)

    rows = client.get_book_summary_by_currency("BTC", "future")

    assert rows == fetcher.response
    assert fetcher.last_path == "get_book_summary_by_currency"
    assert fetcher.last_params == {"currency": "BTC", "kind": "future"}


def test_get_book_summary_rejects_invalid_currency() -> None:
    client = DeribitMarketSummaryClient(fetcher=FakeFetcher([]))
    with pytest.raises(ValueError, match="currency"):
        client.get_book_summary_by_currency("DOGE", "future")


def test_get_book_summary_rejects_invalid_kind() -> None:
    client = DeribitMarketSummaryClient(fetcher=FakeFetcher([]))
    with pytest.raises(ValueError, match="kind"):
        client.get_book_summary_by_currency("BTC", "perpetual")
