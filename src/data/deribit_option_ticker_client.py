"""Thin, injectable wrapper around Deribit's public per-instrument ticker
endpoint:

- GET /api/v2/public/ticker

Unauthenticated, public market-data endpoint (no API keys). Live-verified
against https://www.deribit.com in this session - unlike
src/data/deribit_market_summary_client.py's bulk endpoint, this is the
ONLY Deribit endpoint that returns bid_iv/ask_iv/greeks.delta (see
src/data/deribit_option_instrument.py's module docstring for why a
bounded near-ATM subset, not every active instrument, is fetched this
way).
"""

from __future__ import annotations

import json
import urllib.parse
import urllib.request
from collections.abc import Callable
from typing import Any

DERIBIT_TICKER_URL = "https://www.deribit.com/api/v2/public/ticker"
REQUEST_TIMEOUT_SECS = 15

RawFetcher = Callable[[str], dict[str, Any]]


def default_deribit_ticker_fetcher(instrument_name: str) -> dict[str, Any]:
    """Default `RawFetcher`: GET
    https://www.deribit.com/api/v2/public/ticker?instrument_name=... ,
    returning the JSON-RPC `result` object.
    """
    url = f"{DERIBIT_TICKER_URL}?{urllib.parse.urlencode({'instrument_name': instrument_name})}"
    with urllib.request.urlopen(url, timeout=REQUEST_TIMEOUT_SECS) as resp:
        body = json.loads(resp.read())
    result = body.get("result")
    if not isinstance(result, dict):
        raise RuntimeError(f"unexpected Deribit ticker response shape: {body!r}")
    return result


class DeribitOptionTickerClient:
    """Fetches one instrument's live ticker (mark/bid/ask price, bid_iv/
    ask_iv/mark_iv, greeks.delta, open_interest) at a time - there is no
    bulk-many-instruments variant of this endpoint.
    """

    def __init__(self, fetcher: RawFetcher | None = None) -> None:
        self._fetch = fetcher or default_deribit_ticker_fetcher

    def get_ticker(self, instrument_name: str) -> dict[str, Any]:
        return self._fetch(instrument_name)
