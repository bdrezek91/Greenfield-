"""Thin, injectable wrapper around Bybit's public v5 long/short
account-ratio endpoint (GET /v5/market/account-ratio, exposed by pybit as
`HTTP.get_long_short_ratio`).

Only market-data (unauthenticated) calls are used here. No API keys are
required for this module - see docs/DATA.md.

NOT VERIFIED IN THIS SESSION: same network egress limitation as
src/data/funding_client.py/open_interest_client.py - api.bybit.com and
bybit-exchange.github.io are both blocked from this sandbox. The response
field names assumed in `parse_long_short_ratio_response` (buyRatio,
sellRatio, timestamp) follow Bybit v5's established ratio-endpoint naming
convention used elsewhere in their API (see docs/DATA.md's other Bybit
clients for the same disclosure pattern) but were not confirmed against a
live response here - validate the column mapping on the VPS (which has
unrestricted network access) before trusting it.

Unlike funding-rate-history/open-interest, this endpoint does NOT support
time-window backfill - Bybit only exposes a short recent window per
`limit` (no startTime/endTime pagination surfaced by pybit's method
signature). Like microstructure order-book/trade data, history that
wasn't collected live cannot be recovered later - see
scripts/collect_long_short_ratio.py, the long-running poller that exists
specifically because of this gap.
"""

from __future__ import annotations

from typing import Any, Protocol

MAX_LIMIT = 500

# Bybit's supported ratio aggregation periods - same vocabulary as
# src/data/open_interest_client.py's VALID_INTERVALS.
VALID_PERIODS: tuple[str, ...] = ("5min", "15min", "30min", "1h", "4h", "1d")


class LongShortRatioTransport(Protocol):
    """Anything shaped like pybit's `unified_trading.HTTP` client for this call."""

    def get_long_short_ratio(
        self,
        category: str,
        symbol: str,
        period: str,
        limit: int | None = None,
    ) -> dict[str, Any]: ...


def _default_transport() -> LongShortRatioTransport:
    from pybit.unified_trading import HTTP

    return HTTP()


class BybitLongShortRatioClient:
    """Fetches the current long/short account-ratio snapshot from Bybit -
    there is no pagination/backfill here, only "the most recent `limit`
    readings right now".
    """

    def __init__(self, transport: LongShortRatioTransport | None = None) -> None:
        self._transport = transport or _default_transport()

    def get_long_short_ratio(
        self, category: str, symbol: str, period: str, limit: int = MAX_LIMIT
    ) -> list[dict[str, Any]]:
        if period not in VALID_PERIODS:
            raise ValueError(f"period must be one of {VALID_PERIODS}, got {period!r}")
        response = self._transport.get_long_short_ratio(
            category=category, symbol=symbol, period=period, limit=limit
        )
        ret_code = response.get("retCode")
        if ret_code != 0:
            raise RuntimeError(
                f"Bybit long/short-ratio request failed: retCode={ret_code} "
                f"retMsg={response.get('retMsg')}"
            )
        return response["result"]["list"]
