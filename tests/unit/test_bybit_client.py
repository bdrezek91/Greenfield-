"""BybitKlineClient must unwrap Bybit's response envelope and surface API errors."""

from __future__ import annotations

import pytest

from src.data.bybit_client import BybitKlineClient


class FakeTransport:
    def __init__(self, response: dict) -> None:
        self.response = response
        self.last_call: dict | None = None

    def get_kline(self, **kwargs: object) -> dict:
        self.last_call = kwargs
        return self.response


def test_get_kline_page_returns_list_on_success() -> None:
    transport = FakeTransport(
        {"retCode": 0, "retMsg": "OK", "result": {"list": [["1", "1", "1", "1", "1", "1", "1"]]}}
    )
    client = BybitKlineClient(transport=transport)

    rows = client.get_kline_page(category="linear", symbol="BTCUSDT", interval="60")

    assert rows == [["1", "1", "1", "1", "1", "1", "1"]]
    assert transport.last_call["category"] == "linear"


def test_get_kline_page_raises_on_api_error() -> None:
    transport = FakeTransport({"retCode": 10001, "retMsg": "invalid symbol", "result": {}})
    client = BybitKlineClient(transport=transport)

    with pytest.raises(RuntimeError, match="invalid symbol"):
        client.get_kline_page(category="linear", symbol="NOPE", interval="60")
