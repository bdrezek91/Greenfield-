"""BinanceKlineClient must build correct query params and pass rows
through untouched - the Binance kline counterpart to
test_binance_derivatives_client.py.
"""

from __future__ import annotations

from src.data.binance_klines_client import BinanceKlineClient


class FakeFetcher:
    def __init__(self, response: list[list]) -> None:
        self.response = response
        self.last_params: dict | None = None

    def __call__(self, params: dict) -> list[list]:
        self.last_params = params
        return self.response


def test_get_kline_page_returns_rows_and_builds_params() -> None:
    fetcher = FakeFetcher([[1, "1", "2", "0.5", "1.5", "10"]])
    client = BinanceKlineClient(fetcher=fetcher)

    rows = client.get_kline_page("BTCUSDT", "1h", start_ms=1, end_ms=2, limit=100)

    assert rows == fetcher.response
    assert fetcher.last_params == {
        "symbol": "BTCUSDT",
        "interval": "1h",
        "limit": 100,
        "startTime": 1,
        "endTime": 2,
    }


def test_get_kline_page_omits_time_window_when_not_given() -> None:
    fetcher = FakeFetcher([])
    client = BinanceKlineClient(fetcher=fetcher)

    client.get_kline_page("BTCUSDT", "1h")

    assert "startTime" not in fetcher.last_params
    assert "endTime" not in fetcher.last_params
