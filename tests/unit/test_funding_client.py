"""BybitFundingClient must unwrap Bybit's response envelope and surface API errors."""

from __future__ import annotations

import pytest

from src.data.funding_client import BybitFundingClient


class FakeTransport:
    def __init__(self, response: dict) -> None:
        self.response = response
        self.last_call: dict | None = None

    def get_funding_rate_history(self, **kwargs: object) -> dict:
        self.last_call = kwargs
        return self.response


def test_get_funding_rate_page_returns_list_on_success() -> None:
    transport = FakeTransport(
        {
            "retCode": 0,
            "retMsg": "OK",
            "result": {
                "list": [
                    {
                        "symbol": "BTCUSDT",
                        "fundingRate": "0.0001",
                        "fundingRateTimestamp": "1700000000000",
                    }
                ]
            },
        }
    )
    client = BybitFundingClient(transport=transport)

    rows = client.get_funding_rate_page(category="linear", symbol="BTCUSDT")

    assert rows[0]["fundingRate"] == "0.0001"
    assert transport.last_call["category"] == "linear"
    assert transport.last_call["startTime"] is None


def test_get_funding_rate_page_raises_on_api_error() -> None:
    transport = FakeTransport({"retCode": 10001, "retMsg": "invalid symbol", "result": {}})
    client = BybitFundingClient(transport=transport)

    with pytest.raises(RuntimeError, match="invalid symbol"):
        client.get_funding_rate_page(category="linear", symbol="NOPE")
