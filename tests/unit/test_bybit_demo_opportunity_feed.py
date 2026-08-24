from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

from src.execution.bybit_demo_gateway import BYBIT_PUBLIC_REST_URL
from src.execution.bybit_demo_opportunity_feed import (
    BybitOpportunityFeedError,
    PybitBybitOpportunityFeed,
)

NOW = datetime(2026, 8, 24, 12, 0, tzinfo=UTC)


def _response(rows: list[Any], *, now: datetime = NOW) -> dict[str, Any]:
    return {
        "retCode": 0,
        "retMsg": "OK",
        "time": int(now.timestamp() * 1000),
        "result": {"list": rows},
    }


class FakePublicClient:
    endpoint = BYBIT_PUBLIC_REST_URL

    def __init__(self, *, response_time: datetime = NOW) -> None:
        self.response_time = response_time

    def get_kline(self, **kwargs: Any) -> dict[str, Any]:
        return _response(_price_rows(80, with_volume=True), now=self.response_time)

    def get_public_trade_history(self, **kwargs: Any) -> dict[str, Any]:
        rows = [
            {
                "execId": f"trade-{index}",
                "symbol": "BTCUSDT",
                "price": str(100 + index / 1000),
                "size": "0.01",
                "side": "Buy" if index % 2 else "Sell",
                "time": str(int((NOW - timedelta(milliseconds=index)).timestamp() * 1000)),
            }
            for index in range(300)
        ]
        return _response(rows, now=self.response_time)

    def get_mark_price_kline(self, **kwargs: Any) -> dict[str, Any]:
        return _response(_price_rows(60), now=self.response_time)

    def get_index_price_kline(self, **kwargs: Any) -> dict[str, Any]:
        return _response(_price_rows(60), now=self.response_time)

    def get_open_interest(self, **kwargs: Any) -> dict[str, Any]:
        rows = [
            {
                "timestamp": str(_timestamp_ms(index)),
                "openInterest": str(1_000 + index),
            }
            for index in range(60)
        ]
        return _response(rows, now=self.response_time)

    def get_tickers(self, **kwargs: Any) -> dict[str, Any]:
        return _response([{"symbol": "BTCUSDT", "fundingRate": "0.0001"}], now=self.response_time)

    def get_instruments_info(self, **kwargs: Any) -> dict[str, Any]:
        return _response(
            [{"symbol": "BTCUSDT", "priceFilter": {"tickSize": "0.1"}}],
            now=self.response_time,
        )


def _timestamp_ms(index: int) -> int:
    return int((NOW - timedelta(minutes=5 * index)).timestamp() * 1000)


def _price_rows(count: int, *, with_volume: bool = False) -> list[list[str]]:
    rows = []
    for index in range(count):
        close = 100 + index / 100
        row = [
            str(_timestamp_ms(index)),
            str(close - 0.1),
            str(close + 0.2),
            str(close - 0.2),
            str(close),
        ]
        if with_volume:
            row.extend(["10", "1000"])
        rows.append(row)
    return rows


def test_fetch_builds_one_strict_scanner_snapshot() -> None:
    snapshot = PybitBybitOpportunityFeed(client=FakePublicClient()).fetch(
        symbol="BTCUSDT", observed_at_utc=NOW
    )

    assert snapshot.symbol == "BTCUSDT"
    assert len(snapshot.candles) == 80
    assert len(snapshot.trades) == 300
    assert len(snapshot.derivatives) == 60
    assert snapshot.price_tick == 0.1
    assert snapshot.candles["timestamp"].is_monotonic_increasing
    assert snapshot.derivatives["timestamp"].is_monotonic_increasing


def test_feed_refuses_wrong_endpoint() -> None:
    client = FakePublicClient()
    client.endpoint = "https://api-testnet.bybit.com"

    with pytest.raises(BybitOpportunityFeedError, match="non-mainnet"):
        PybitBybitOpportunityFeed(client=client)


def test_feed_refuses_stale_provider_response() -> None:
    feed = PybitBybitOpportunityFeed(
        client=FakePublicClient(response_time=NOW - timedelta(minutes=2))
    )

    with pytest.raises(BybitOpportunityFeedError, match="stale or from the future"):
        feed.fetch(symbol="BTCUSDT", observed_at_utc=NOW)
