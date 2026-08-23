"""BinanceOpenInterestClient/BinanceLongShortRatioClient must build correct
query params, pass rows through untouched, and reject invalid periods -
the Binance counterpart to test_long_short_ratio_client.py /
test_open_interest_client.py.
"""

from __future__ import annotations

import pytest

from src.data.binance_derivatives_client import (
    BinanceLongShortRatioClient,
    BinanceOpenInterestClient,
)


class FakeFetcher:
    def __init__(self, response: list[dict]) -> None:
        self.response = response
        self.last_path: str | None = None
        self.last_params: dict | None = None

    def __call__(self, path: str, params: dict) -> list[dict]:
        self.last_path = path
        self.last_params = params
        return self.response


def test_open_interest_history_returns_rows_and_builds_params() -> None:
    fetcher = FakeFetcher([{"symbol": "BTCUSDT", "sumOpenInterest": "100000", "timestamp": "1"}])
    client = BinanceOpenInterestClient(fetcher=fetcher)

    rows = client.get_open_interest_history("BTCUSDT", "5m", limit=100, start_ms=1, end_ms=2)

    assert rows == fetcher.response
    assert fetcher.last_path == "openInterestHist"
    assert fetcher.last_params == {
        "symbol": "BTCUSDT",
        "period": "5m",
        "limit": 100,
        "startTime": 1,
        "endTime": 2,
    }


def test_open_interest_history_omits_time_window_when_not_given() -> None:
    fetcher = FakeFetcher([])
    client = BinanceOpenInterestClient(fetcher=fetcher)

    client.get_open_interest_history("BTCUSDT", "5m")

    assert "startTime" not in fetcher.last_params
    assert "endTime" not in fetcher.last_params


def test_open_interest_history_rejects_invalid_period() -> None:
    client = BinanceOpenInterestClient(fetcher=FakeFetcher([]))
    with pytest.raises(ValueError, match="period"):
        client.get_open_interest_history("BTCUSDT", "9m")


def test_long_short_ratio_history_returns_rows_and_builds_params() -> None:
    fetcher = FakeFetcher(
        [{"symbol": "BTCUSDT", "longAccount": "0.5", "shortAccount": "0.5", "timestamp": "1"}]
    )
    client = BinanceLongShortRatioClient(fetcher=fetcher)

    rows = client.get_long_short_ratio_history("BTCUSDT", "5m", limit=50)

    assert rows == fetcher.response
    assert fetcher.last_path == "globalLongShortAccountRatio"
    assert fetcher.last_params == {"symbol": "BTCUSDT", "period": "5m", "limit": 50}


def test_long_short_ratio_history_rejects_invalid_period() -> None:
    client = BinanceLongShortRatioClient(fetcher=FakeFetcher([]))
    with pytest.raises(ValueError, match="period"):
        client.get_long_short_ratio_history("BTCUSDT", "9m")
