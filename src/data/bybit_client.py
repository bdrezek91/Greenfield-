"""Thin, injectable wrapper around Bybit's public v5 kline endpoint.

Only market-data (unauthenticated) calls are used here. No API keys are
required for this module - see docs/DATA.md.
"""

from __future__ import annotations

from typing import Any, Protocol

MAX_LIMIT = 1000


class KlineTransport(Protocol):
    """Anything shaped like pybit's `unified_trading.HTTP` client for this call."""

    def get_kline(
        self,
        category: str,
        symbol: str,
        interval: str,
        start: int | None = None,
        end: int | None = None,
        limit: int | None = None,
    ) -> dict[str, Any]: ...


def _default_transport() -> KlineTransport:
    from pybit.unified_trading import HTTP

    return HTTP()


class BybitKlineClient:
    """Fetches raw kline pages from Bybit. Pagination lives in `ingest.py`."""

    def __init__(self, transport: KlineTransport | None = None) -> None:
        self._transport = transport or _default_transport()

    def get_kline_page(
        self,
        category: str,
        symbol: str,
        interval: str,
        start_ms: int | None = None,
        end_ms: int | None = None,
        limit: int = MAX_LIMIT,
    ) -> list[list[str]]:
        response = self._transport.get_kline(
            category=category,
            symbol=symbol,
            interval=interval,
            start=start_ms,
            end=end_ms,
            limit=limit,
        )
        ret_code = response.get("retCode")
        if ret_code != 0:
            raise RuntimeError(
                f"Bybit kline request failed: retCode={ret_code} "
                f"retMsg={response.get('retMsg')}"
            )
        return response["result"]["list"]
