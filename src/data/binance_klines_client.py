"""Thin, injectable wrapper around Binance USDT-M futures' public kline
endpoint.

- GET /fapi/v1/klines

Unauthenticated, public market-data endpoint (no API keys). Live-verified
against https://fapi.binance.com in this session. Response shape is an
array of arrays (not objects like Bybit's enveloped response):
`[open_time_ms, open, high, low, close, volume, close_time_ms,
quote_volume, trade_count, taker_buy_base_vol, taker_buy_quote_vol,
ignore]` - only the first 6 fields are used (see
src/data/ingest_binance_klines.py).

No third-party SDK dependency: uses `urllib.request` directly, the same
pattern as every other Binance client in this project.
"""

from __future__ import annotations

import json
import urllib.parse
import urllib.request
from collections.abc import Callable
from typing import Any

BINANCE_KLINES_URL = "https://fapi.binance.com/fapi/v1/klines"
MAX_LIMIT = 1500
REQUEST_TIMEOUT_SECS = 10

RawFetcher = Callable[[dict[str, str | int]], list[list[Any]]]


def default_binance_klines_fetcher(params: dict[str, str | int]) -> list[list[Any]]:
    """Default `RawFetcher`: GET https://fapi.binance.com/fapi/v1/klines
    with `params` as the query string, parsed as a JSON array of arrays.
    """
    url = f"{BINANCE_KLINES_URL}?{urllib.parse.urlencode(params)}"
    with urllib.request.urlopen(url, timeout=REQUEST_TIMEOUT_SECS) as resp:
        body = json.loads(resp.read())
    if not isinstance(body, list):
        raise RuntimeError(f"unexpected Binance klines response shape: {body!r}")
    return body


class BinanceKlineClient:
    """Fetches raw kline pages from Binance. Pagination lives in
    src/data/ingest_binance_klines.py."""

    def __init__(self, fetcher: RawFetcher | None = None) -> None:
        self._fetch = fetcher or default_binance_klines_fetcher

    def get_kline_page(
        self,
        symbol: str,
        interval: str,
        start_ms: int | None = None,
        end_ms: int | None = None,
        limit: int = MAX_LIMIT,
    ) -> list[list[Any]]:
        params: dict[str, str | int] = {"symbol": symbol, "interval": interval, "limit": limit}
        if start_ms is not None:
            params["startTime"] = start_ms
        if end_ms is not None:
            params["endTime"] = end_ms
        return self._fetch(params)
