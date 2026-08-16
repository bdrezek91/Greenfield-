"""Thin, injectable wrapper around Bybit's public v5 funding-rate-history
endpoint (GET /v5/market/funding/history).

Only market-data (unauthenticated) calls are used here. No API keys are
required for this module - see docs/DATA.md.

NOT VERIFIED IN THIS SESSION: this session's network egress policy blocks
api.bybit.com (see src/data/bybit_client.py's sibling module and
docs/DATA.md for the same limitation). Parameter names here
(startTime/endTime, not start/end) follow Bybit's public v5 API
documentation directly, since pybit's funding-rate-history method mirrors
the REST param names 1:1 (unlike the kline endpoint, which uses
start/end) - validate against a live pybit call on a machine with
unrestricted network access before relying on this.
"""

from __future__ import annotations

from typing import Any, Protocol

MAX_LIMIT = 200


class FundingRateTransport(Protocol):
    """Anything shaped like pybit's `unified_trading.HTTP` client for this call."""

    def get_funding_rate_history(
        self,
        category: str,
        symbol: str,
        startTime: int | None = None,
        endTime: int | None = None,
        limit: int | None = None,
    ) -> dict[str, Any]: ...


def _default_transport() -> FundingRateTransport:
    from pybit.unified_trading import HTTP

    return HTTP()


class BybitFundingClient:
    """Fetches raw funding-rate-history pages from Bybit. Pagination lives
    in `src/data/ingest_funding.py`.
    """

    def __init__(self, transport: FundingRateTransport | None = None) -> None:
        self._transport = transport or _default_transport()

    def get_funding_rate_page(
        self,
        category: str,
        symbol: str,
        start_ms: int | None = None,
        end_ms: int | None = None,
        limit: int = MAX_LIMIT,
    ) -> list[dict[str, Any]]:
        response = self._transport.get_funding_rate_history(
            category=category,
            symbol=symbol,
            startTime=start_ms,
            endTime=end_ms,
            limit=limit,
        )
        ret_code = response.get("retCode")
        if ret_code != 0:
            raise RuntimeError(
                f"Bybit funding-rate-history request failed: retCode={ret_code} "
                f"retMsg={response.get('retMsg')}"
            )
        return response["result"]["list"]
