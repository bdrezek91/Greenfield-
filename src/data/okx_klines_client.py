"""Thin, injectable wrapper around OKX's public historical-candles
endpoint.

- GET /api/v5/market/history-candles

Unauthenticated, public market-data endpoint (no API keys). Live-verified
against https://www.okx.com in this session. Response shape is an array
of arrays, NEWEST-FIRST (descending by timestamp) - the OPPOSITE
convention from Binance's ascending pages (see
src/data/ingest_binance_klines.py), but the SAME convention as Bybit's
(see src/data/bybit_client.py/ingest.py):
`[ts_ms, open, high, low, close, vol, volCcy, volCcyQuote, confirm]` -
`vol` is in CONTRACTS (OKX perpetual swaps are contract-denominated, see
configs/instruments_okx.yaml's module comment), not directly comparable
to Bybit/Binance's base-currency volume, so `volCcy` (already base
currency) is used instead - see src/data/ingest_okx_klines.py. `confirm`
("0"/"1") marks whether a candle is still forming; only "1" (closed)
candles are kept.

No third-party SDK dependency: uses `urllib.request` directly, the same
pattern as every other client in this project.
"""

from __future__ import annotations

import json
import urllib.parse
import urllib.request
from collections.abc import Callable
from typing import Any

OKX_HISTORY_CANDLES_URL = "https://www.okx.com/api/v5/market/history-candles"
MAX_LIMIT = 300  # live-verified this session: 300 accepted, 500 silently capped to 300
REQUEST_TIMEOUT_SECS = 10

RawFetcher = Callable[[dict[str, str | int]], list[list[Any]]]


def default_okx_klines_fetcher(params: dict[str, str | int]) -> list[list[Any]]:
    """Default `RawFetcher`: GET
    https://www.okx.com/api/v5/market/history-candles with `params` as the
    query string, returning the JSON-RPC `data` array of arrays.
    """
    url = f"{OKX_HISTORY_CANDLES_URL}?{urllib.parse.urlencode(params)}"
    with urllib.request.urlopen(url, timeout=REQUEST_TIMEOUT_SECS) as resp:
        body = json.loads(resp.read())
    if body.get("code") != "0":
        raise RuntimeError(f"OKX history-candles request failed: {body!r}")
    data = body.get("data")
    if not isinstance(data, list):
        raise RuntimeError(f"unexpected OKX history-candles response shape: {body!r}")
    return data


class OkxKlineClient:
    """Fetches raw kline pages from OKX. Pagination lives in
    src/data/ingest_okx_klines.py."""

    def __init__(self, fetcher: RawFetcher | None = None) -> None:
        self._fetch = fetcher or default_okx_klines_fetcher

    def get_kline_page(
        self,
        inst_id: str,
        bar: str,
        after_ms: int | None = None,
        limit: int = MAX_LIMIT,
    ) -> list[list[Any]]:
        """`after_ms`, if given, returns only candles strictly OLDER than
        it (OKX's own pagination cursor semantics, live-verified this
        session) - the backward-paging equivalent of Bybit's `end_ms`.
        """
        params: dict[str, str | int] = {"instId": inst_id, "bar": bar, "limit": limit}
        if after_ms is not None:
            params["after"] = after_ms
        return self._fetch(params)
