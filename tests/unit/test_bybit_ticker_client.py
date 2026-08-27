"""BybitTickerClient must unwrap Bybit's {retCode, retMsg, result}
envelope, surface API errors, and reject a malformed ticker list - the
Bybit counterpart to test_okx_derivatives_client.py."""

from __future__ import annotations

import pytest

from src.data.bybit_ticker_client import BybitTickerClient


class FakeFetcher:
    def __init__(self, response: dict) -> None:
        self.response = response
        self.last_path: str | None = None
        self.last_params: dict | None = None

    def __call__(self, path: str, params: dict) -> dict:
        self.last_path = path
        self.last_params = params
        return self.response


def test_get_ticker_returns_single_row_and_builds_params() -> None:
    row = {"symbol": "BTCUSDT", "bid1Price": "100.0", "ask1Price": "100.1"}
    fetcher = FakeFetcher({"list": [row]})
    client = BybitTickerClient(fetcher=fetcher)

    result = client.get_ticker("BTCUSDT")

    assert result == row
    assert fetcher.last_path == "market/tickers"
    assert fetcher.last_params == {"category": "linear", "symbol": "BTCUSDT"}


def test_get_ticker_rejects_empty_or_multi_row_list() -> None:
    client = BybitTickerClient(fetcher=FakeFetcher({"list": []}))
    with pytest.raises(RuntimeError, match="expected exactly one"):
        client.get_ticker("BTCUSDT")

    client = BybitTickerClient(fetcher=FakeFetcher({"list": [{}, {}]}))
    with pytest.raises(RuntimeError, match="expected exactly one"):
        client.get_ticker("BTCUSDT")
