"""BybitOpenInterestClient must unwrap Bybit's response envelope, surface API
errors, and reject unknown intervals.
"""

from __future__ import annotations

import pytest

from src.data.open_interest_client import BybitOpenInterestClient


class FakeTransport:
    def __init__(self, response: dict) -> None:
        self.response = response
        self.last_call: dict | None = None

    def get_open_interest(self, **kwargs: object) -> dict:
        self.last_call = kwargs
        return self.response


def test_get_open_interest_page_returns_list_and_cursor_on_success() -> None:
    transport = FakeTransport(
        {
            "retCode": 0,
            "retMsg": "OK",
            "result": {
                "list": [{"openInterest": "100.5", "timestamp": "1700000000000"}],
                "nextPageCursor": "abc123",
            },
        }
    )
    client = BybitOpenInterestClient(transport=transport)

    rows, cursor = client.get_open_interest_page(
        category="linear", symbol="BTCUSDT", interval_time="1h"
    )

    assert rows[0]["openInterest"] == "100.5"
    assert cursor == "abc123"
    assert transport.last_call["intervalTime"] == "1h"


def test_get_open_interest_page_returns_none_cursor_when_absent() -> None:
    transport = FakeTransport(
        {"retCode": 0, "retMsg": "OK", "result": {"list": [], "nextPageCursor": ""}}
    )
    client = BybitOpenInterestClient(transport=transport)

    rows, cursor = client.get_open_interest_page(
        category="linear", symbol="BTCUSDT", interval_time="1h"
    )

    assert rows == []
    assert cursor is None


def test_get_open_interest_page_raises_on_api_error() -> None:
    transport = FakeTransport({"retCode": 10001, "retMsg": "invalid symbol", "result": {}})
    client = BybitOpenInterestClient(transport=transport)

    with pytest.raises(RuntimeError, match="invalid symbol"):
        client.get_open_interest_page(category="linear", symbol="NOPE", interval_time="1h")


def test_get_open_interest_page_rejects_unknown_interval() -> None:
    client = BybitOpenInterestClient(transport=FakeTransport({}))

    with pytest.raises(ValueError, match="interval_time must be one of"):
        client.get_open_interest_page(category="linear", symbol="BTCUSDT", interval_time="7h")
