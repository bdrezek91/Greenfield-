"""Thin, injectable wrappers around OKX's public derivatives-statistics
endpoints:

- GET /api/v5/public/open-interest
- GET /api/v5/rubik/stat/contracts/long-short-account-ratio-contract

Both are unauthenticated, public market-data endpoints (no API keys) and
were live-verified against https://www.okx.com in this session.
open-interest returns the current snapshot only (no time-window history
parameter, unlike Binance's openInterestHist) - each poll is one new,
timestamped reading, same "poll and dedup by timestamp" shape as Bybit's
long/short poller. long-short-account-ratio-contract returns a genuine
historical series of `[timestamp, ratio]` pairs, unlike Binance's object
rows - OKX's own response shape, not normalized to match Binance's here
(see src/data/schema_okx_derivatives.py's module docstring for why).

No third-party SDK dependency: uses `urllib.request` directly, the same
pattern as src/data/binance_derivatives_client.py.
"""

from __future__ import annotations

import json
import urllib.parse
import urllib.request
from collections.abc import Callable
from typing import Any

OKX_API_BASE = "https://www.okx.com/api/v5"
REQUEST_TIMEOUT_SECS = 10

# OKX's supported aggregation periods for the long/short ratio endpoint.
VALID_PERIODS: tuple[str, ...] = ("5m", "15m", "30m", "1H", "2H", "4H", "12H", "1D")

RawFetcher = Callable[[str, dict[str, str | int]], list[Any]]


def default_okx_fetcher(path: str, params: dict[str, str | int]) -> list[Any]:
    """Default `RawFetcher`: GET https://www.okx.com/api/v5/{path} with
    `params` as the query string, unwrapping OKX's `{code, data, msg}`
    envelope and returning `data`.
    """
    url = f"{OKX_API_BASE}/{path}?{urllib.parse.urlencode(params)}"
    with urllib.request.urlopen(url, timeout=REQUEST_TIMEOUT_SECS) as resp:
        body = json.loads(resp.read())
    if body.get("code") != "0":
        raise RuntimeError(
            f"OKX {path} request failed: code={body.get('code')} msg={body.get('msg')}"
        )
    data = body.get("data")
    if not isinstance(data, list):
        raise RuntimeError(f"unexpected OKX {path} response shape: {body!r}")
    return data


def _validate_period(period: str) -> None:
    if period not in VALID_PERIODS:
        raise ValueError(f"period must be one of {VALID_PERIODS}, got {period!r}")


class OkxOpenInterestClient:
    """Fetches the current open-interest snapshot for one instrument from
    OKX's `/public/open-interest` endpoint - there is no pagination/
    backfill here, only "the current reading right now" (like Bybit's
    long/short-ratio endpoint).
    """

    def __init__(self, fetcher: RawFetcher | None = None) -> None:
        self._fetch = fetcher or default_okx_fetcher

    def get_open_interest_snapshot(self, inst_id: str) -> list[Any]:
        return self._fetch("public/open-interest", {"instType": "SWAP", "instId": inst_id})


class OkxLongShortRatioClient:
    """Fetches long/short account-ratio history from OKX's
    `rubik/stat/contracts/long-short-account-ratio-contract` endpoint.
    """

    def __init__(self, fetcher: RawFetcher | None = None) -> None:
        self._fetch = fetcher or default_okx_fetcher

    def get_long_short_ratio_history(
        self, inst_id: str, period: str, *, limit: int | None = None
    ) -> list[Any]:
        _validate_period(period)
        params: dict[str, str | int] = {"instId": inst_id, "period": period}
        if limit is not None:
            params["limit"] = limit
        return self._fetch("rubik/stat/contracts/long-short-account-ratio-contract", params)
