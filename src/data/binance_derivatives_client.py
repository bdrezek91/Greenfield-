"""Thin, injectable wrappers around Binance USDT-M futures' public
derivatives-statistics endpoints:

- GET /futures/data/openInterestHist
- GET /futures/data/globalLongShortAccountRatio

Both are unauthenticated, public market-data endpoints (no API keys) and
were live-verified against https://fapi.binance.com in this session
(unlike the Bybit clients in src/data/open_interest_client.py /
long_short_ratio_client.py, which carry a "NOT VERIFIED IN THIS SESSION"
disclosure because their sandbox blocked api.bybit.com).

Both endpoints share the same request shape (symbol/period/limit, optional
startTime/endTime) and only retain roughly 30 days of history - beyond
that window there is nothing to backfill, only what a live poller collects
going forward (see src/data/binance_derivatives_collector.py). No
third-party SDK dependency: uses `urllib.request` directly, the same
dependency-free HTTP pattern already established in
src/data/binance_raw_collector.py's `default_depth_snapshot_fetcher`.
"""

from __future__ import annotations

import json
import urllib.parse
import urllib.request
from collections.abc import Callable
from typing import Any

BINANCE_FUTURES_DATA_BASE = "https://fapi.binance.com/futures/data"
MAX_LIMIT = 500
REQUEST_TIMEOUT_SECS = 10

# Binance's supported aggregation periods for both of these endpoints.
VALID_PERIODS: tuple[str, ...] = ("5m", "15m", "30m", "1h", "2h", "4h", "6h", "12h", "1d")

RawFetcher = Callable[[str, dict[str, str | int]], list[dict[str, Any]]]


def default_binance_futures_data_fetcher(
    path: str, params: dict[str, str | int]
) -> list[dict[str, Any]]:
    """Default `RawFetcher`: GET https://fapi.binance.com/futures/data/{path}
    with `params` as the query string, parsed as a JSON list of rows.
    """
    url = f"{BINANCE_FUTURES_DATA_BASE}/{path}?{urllib.parse.urlencode(params)}"
    with urllib.request.urlopen(url, timeout=REQUEST_TIMEOUT_SECS) as resp:
        body = json.loads(resp.read())
    if not isinstance(body, list):
        raise RuntimeError(f"unexpected Binance {path} response shape: {body!r}")
    return body


def _validate_period(period: str) -> None:
    if period not in VALID_PERIODS:
        raise ValueError(f"period must be one of {VALID_PERIODS}, got {period!r}")


class BinanceOpenInterestClient:
    """Fetches open-interest history pages from Binance's
    `openInterestHist` endpoint (aggregated `sumOpenInterest`/
    `sumOpenInterestValue`, not the single-snapshot `/fapi/v1/openInterest`
    - the aggregated endpoint's timestamped series fits this project's
    poll-and-dedup-by-timestamp pattern, matching Bybit's OI shape).
    """

    def __init__(self, fetcher: RawFetcher | None = None) -> None:
        self._fetch = fetcher or default_binance_futures_data_fetcher

    def get_open_interest_history(
        self,
        symbol: str,
        period: str,
        *,
        limit: int = MAX_LIMIT,
        start_ms: int | None = None,
        end_ms: int | None = None,
    ) -> list[dict[str, Any]]:
        _validate_period(period)
        params: dict[str, str | int] = {"symbol": symbol, "period": period, "limit": limit}
        if start_ms is not None:
            params["startTime"] = start_ms
        if end_ms is not None:
            params["endTime"] = end_ms
        return self._fetch("openInterestHist", params)


class BinanceLongShortRatioClient:
    """Fetches global long/short account-ratio history pages from
    Binance's `globalLongShortAccountRatio` endpoint.
    """

    def __init__(self, fetcher: RawFetcher | None = None) -> None:
        self._fetch = fetcher or default_binance_futures_data_fetcher

    def get_long_short_ratio_history(
        self,
        symbol: str,
        period: str,
        *,
        limit: int = MAX_LIMIT,
        start_ms: int | None = None,
        end_ms: int | None = None,
    ) -> list[dict[str, Any]]:
        _validate_period(period)
        params: dict[str, str | int] = {"symbol": symbol, "period": period, "limit": limit}
        if start_ms is not None:
            params["startTime"] = start_ms
        if end_ms is not None:
            params["endTime"] = end_ms
        return self._fetch("globalLongShortAccountRatio", params)
