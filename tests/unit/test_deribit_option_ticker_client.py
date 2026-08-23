"""DeribitOptionTickerClient must pass the instrument name through
untouched and return the fetcher's result as-is - the per-instrument
counterpart to test_deribit_market_summary_client.py's bulk client.
"""

from __future__ import annotations

from src.data.deribit_option_ticker_client import DeribitOptionTickerClient


class FakeFetcher:
    def __init__(self, response: dict) -> None:
        self.response = response
        self.last_instrument_name: str | None = None

    def __call__(self, instrument_name: str) -> dict:
        self.last_instrument_name = instrument_name
        return self.response


def test_get_ticker_returns_the_result_and_passes_the_instrument_name() -> None:
    fetcher = FakeFetcher({"mark_iv": 45.0, "bid_iv": 42.0, "ask_iv": 48.0})
    client = DeribitOptionTickerClient(fetcher=fetcher)

    result = client.get_ticker("BTC-24AUG26-100000-C")

    assert result == fetcher.response
    assert fetcher.last_instrument_name == "BTC-24AUG26-100000-C"
