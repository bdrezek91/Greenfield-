"""Thin, injectable wrapper around Deribit's public per-currency market
summary endpoint:

- GET /api/v2/public/get_book_summary_by_currency

Unauthenticated, public market-data endpoint (no API keys). Live-verified
against https://www.deribit.com in this session - see
src/data/schema_deribit_market_summary.py's module docstring for why this
endpoint (not per-instrument WS subscriptions) is the right shape for
dated-futures/options coverage at Deribit's actual instrument count.
"""

from __future__ import annotations

import json
import urllib.parse
import urllib.request
from collections.abc import Callable
from typing import Any

DERIBIT_API_BASE = "https://www.deribit.com/api/v2/public"
REQUEST_TIMEOUT_SECS = 15

VALID_KINDS: tuple[str, ...] = ("future", "option")
VALID_CURRENCIES: tuple[str, ...] = ("BTC", "ETH")

RawFetcher = Callable[[str, dict[str, str]], list[dict[str, Any]]]


def default_deribit_fetcher(path: str, params: dict[str, str]) -> list[dict[str, Any]]:
    """Default `RawFetcher`: GET https://www.deribit.com/api/v2/public/{path}
    with `params` as the query string, returning the JSON-RPC `result` list.
    """
    url = f"{DERIBIT_API_BASE}/{path}?{urllib.parse.urlencode(params)}"
    with urllib.request.urlopen(url, timeout=REQUEST_TIMEOUT_SECS) as resp:
        body = json.loads(resp.read())
    result = body.get("result")
    if not isinstance(result, list):
        raise RuntimeError(f"unexpected Deribit {path} response shape: {body!r}")
    return result


class DeribitMarketSummaryClient:
    """Fetches a full per-currency, per-kind instrument summary snapshot
    (perpetual + dated futures, or every active option series) in one call.
    """

    def __init__(self, fetcher: RawFetcher | None = None) -> None:
        self._fetch = fetcher or default_deribit_fetcher

    def get_book_summary_by_currency(self, currency: str, kind: str) -> list[dict[str, Any]]:
        if currency not in VALID_CURRENCIES:
            raise ValueError(f"currency must be one of {VALID_CURRENCIES}, got {currency!r}")
        if kind not in VALID_KINDS:
            raise ValueError(f"kind must be one of {VALID_KINDS}, got {kind!r}")
        return self._fetch(
            "get_book_summary_by_currency", {"currency": currency, "kind": kind}
        )
