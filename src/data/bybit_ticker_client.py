"""Thin, injectable wrapper around Bybit's public `GET /v5/market/tickers`
endpoint - the only source of a live EXECUTABLE Bybit quote (bid1Price/
ask1Price) this project has outside the full tick-level raw collector.
Public market data only, no API keys.

Added specifically to unblock `src.engines.neutral_market`'s cross-
exchange funding coarse screen (GREENFIELD PROFITABILITY PIVOT item 5):
Bybit's raw collector captures L2 ticks but has no lightweight "give me
the current top of book" call, unlike every other REST client in this
project. This endpoint also happens to return markPrice/indexPrice/
fundingRate/openInterest/fundingIntervalHour in the same call - the same
"one call, several fields" shape as Hyperliquid's `metaAndAssetCtxs`
(see src/data/hyperliquid_client.py).

Live-verified against https://api.bybit.com in this session (2026-08-27).
"""

from __future__ import annotations

import json
import urllib.parse
import urllib.request
from collections.abc import Callable
from typing import Any

BYBIT_API_BASE = "https://api.bybit.com/v5"
REQUEST_TIMEOUT_SECS = 10

RawFetcher = Callable[[str, dict[str, str]], dict[str, Any]]


def default_bybit_ticker_fetcher(path: str, params: dict[str, str]) -> dict[str, Any]:
    """Default `RawFetcher`: GET https://api.bybit.com/v5/{path} with
    `params` as the query string, unwrapping Bybit's
    `{retCode, retMsg, result}` envelope and returning `result`."""
    url = f"{BYBIT_API_BASE}/{path}?{urllib.parse.urlencode(params)}"
    request = urllib.request.Request(url)
    with urllib.request.urlopen(request, timeout=REQUEST_TIMEOUT_SECS) as resp:
        body = json.loads(resp.read())
    if body.get("retCode") != 0:
        raise RuntimeError(
            f"Bybit {path} request failed: retCode={body.get('retCode')} "
            f"retMsg={body.get('retMsg')}"
        )
    result = body.get("result")
    if not isinstance(result, dict):
        raise RuntimeError(f"unexpected Bybit {path} response shape: {body!r}")
    return result


class BybitTickerClient:
    """Fetches the current ticker (BBO, mark/index price, funding rate,
    open interest) for one linear-perpetual symbol."""

    def __init__(self, fetcher: RawFetcher | None = None) -> None:
        self._fetch = fetcher or default_bybit_ticker_fetcher

    def get_ticker(self, symbol: str, *, category: str = "linear") -> dict[str, Any]:
        result = self._fetch("market/tickers", {"category": category, "symbol": symbol})
        rows = result.get("list")
        if not isinstance(rows, list) or len(rows) != 1:
            raise RuntimeError(f"expected exactly one ticker row for {symbol}, got {result!r}")
        return rows[0]
