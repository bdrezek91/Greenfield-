"""Thin, injectable wrapper around Bybit's public v5 open-interest endpoint
(GET /v5/market/open-interest).

Only market-data (unauthenticated) calls are used here. No API keys are
required for this module - see docs/DATA.md.

NOT VERIFIED IN THIS SESSION: same network egress limitation as
src/data/funding_client.py and src/data/bybit_client.py - validate on a
machine with unrestricted network access before relying on this.

Unlike kline/funding-rate-history, this endpoint is cursor-paginated
(`result.nextPageCursor`), not time-window paginated - see
`src/data/ingest_open_interest.py`.
"""

from __future__ import annotations

from typing import Any, Protocol

MAX_LIMIT = 200

# Bybit's supported open-interest aggregation intervals.
VALID_INTERVALS: tuple[str, ...] = ("5min", "15min", "30min", "1h", "4h", "1d")


class OpenInterestTransport(Protocol):
    """Anything shaped like pybit's `unified_trading.HTTP` client for this call."""

    def get_open_interest(
        self,
        category: str,
        symbol: str,
        intervalTime: str,
        startTime: int | None = None,
        endTime: int | None = None,
        limit: int | None = None,
        cursor: str | None = None,
    ) -> dict[str, Any]: ...


def _default_transport() -> OpenInterestTransport:
    from pybit.unified_trading import HTTP

    return HTTP()


class BybitOpenInterestClient:
    """Fetches raw open-interest pages from Bybit. Pagination lives in
    `src/data/ingest_open_interest.py`.
    """

    def __init__(self, transport: OpenInterestTransport | None = None) -> None:
        self._transport = transport or _default_transport()

    def get_open_interest_page(
        self,
        category: str,
        symbol: str,
        interval_time: str,
        start_ms: int | None = None,
        end_ms: int | None = None,
        limit: int = MAX_LIMIT,
        cursor: str | None = None,
    ) -> tuple[list[dict[str, Any]], str | None]:
        if interval_time not in VALID_INTERVALS:
            raise ValueError(
                f"interval_time must be one of {VALID_INTERVALS}, got {interval_time!r}"
            )
        response = self._transport.get_open_interest(
            category=category,
            symbol=symbol,
            intervalTime=interval_time,
            startTime=start_ms,
            endTime=end_ms,
            limit=limit,
            cursor=cursor,
        )
        ret_code = response.get("retCode")
        if ret_code != 0:
            raise RuntimeError(
                f"Bybit open-interest request failed: retCode={ret_code} "
                f"retMsg={response.get('retMsg')}"
            )
        result = response["result"]
        next_cursor = result.get("nextPageCursor") or None
        return result["list"], next_cursor
