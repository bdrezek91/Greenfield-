"""BybitLongShortRatioClient must unwrap Bybit's response envelope,
surface API errors, and reject invalid periods."""

from __future__ import annotations

import pytest

from src.data.long_short_ratio_client import BybitLongShortRatioClient


class FakeTransport:
    def __init__(self, response: dict) -> None:
        self.response = response
        self.last_call: dict | None = None

    def get_long_short_ratio(self, **kwargs: object) -> dict:
        self.last_call = kwargs
        return self.response


def test_get_long_short_ratio_returns_list_on_success() -> None:
    transport = FakeTransport(
        {
            "retCode": 0,
            "retMsg": "OK",
            "result": {
                "list": [
                    {
                        "symbol": "BTCUSDT",
                        "buyRatio": "0.55",
                        "sellRatio": "0.45",
                        "timestamp": "1700000000000",
                    }
                ]
            },
        }
    )
    client = BybitLongShortRatioClient(transport=transport)

    rows = client.get_long_short_ratio(category="linear", symbol="BTCUSDT", period="5min")

    assert rows[0]["buyRatio"] == "0.55"
    assert transport.last_call["category"] == "linear"
    assert transport.last_call["period"] == "5min"


def test_get_long_short_ratio_raises_on_api_error() -> None:
    transport = FakeTransport({"retCode": 10001, "retMsg": "invalid symbol", "result": {}})
    client = BybitLongShortRatioClient(transport=transport)

    with pytest.raises(RuntimeError, match="invalid symbol"):
        client.get_long_short_ratio(category="linear", symbol="NOPE", period="5min")


def test_get_long_short_ratio_rejects_invalid_period() -> None:
    client = BybitLongShortRatioClient(transport=FakeTransport({}))
    with pytest.raises(ValueError, match="period"):
        client.get_long_short_ratio(category="linear", symbol="BTCUSDT", period="9min")
