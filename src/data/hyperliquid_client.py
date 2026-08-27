"""Thin, injectable wrapper around Hyperliquid's public `/info` endpoint -
read-only research data only (funding, BBO, mark/index price, open
interest, predicted funding across venues). No order placement, no
authenticated/signed requests, no full-depth L2 collector - this client
exists to feed `src.engines.neutral_market`'s cross-exchange funding
research, not to trade or to replicate a venue's whole book.

Unlike Bybit/Binance/OKX (one endpoint per dataset), Hyperliquid exposes
everything through a single `POST https://api.hyperliquid.xyz/info` with
a `type` discriminator in the JSON body - so `RawFetcher` here takes one
request-body dict rather than OKX/Binance's `(path, params)` shape.

Live-verified against https://api.hyperliquid.xyz/info in this session
(2026-08-27):
- `{"type": "metaAndAssetCtxs"}` -> `[{"universe": [...]}, [asset_ctx, ...]]`,
  asset_ctx (index-aligned with `universe`) has funding/openInterest/
  markPx/oraclePx/midPx/premium/dayNtlVlm/dayBaseVlm/prevDayPx/impactPxs.
- `{"type": "fundingHistory", "coin": "BTC", "startTime": ms, "endTime": ms}`
  -> `[{"coin", "fundingRate", "premium", "time"}, ...]`, a genuine
  historical series (unlike `metaAndAssetCtxs`'s single current reading).
- `{"type": "predictedFundings"}` -> `[[coin, [[venue, {"fundingRate",
  "nextFundingTime", "fundingIntervalHours"}], ...]], ...]` for ALL
  coins in one call. For BTC/ETH/SOL the venues observed were
  `BinPerp`/`HlPerp`/`BybitPerp` - no `OkxPerp` entry was present, so
  this does not fill the OKX funding gap (see
  docs/CLAUDE_CODE_CONTINUATION.md's data-inventory checkpoint).
- `{"type": "l2Book", "coin": "BTC"}` -> `{"coin", "time", "levels":
  [[bid_level, ...], [ask_level, ...]]}`, each level `{"px", "sz", "n"}`,
  bids first then asks. Only the top level of each side is used here
  (BBO) - deliberately not a full-depth collector.
"""

from __future__ import annotations

import json
import urllib.request
from collections.abc import Callable
from typing import Any

HYPERLIQUID_INFO_URL = "https://api.hyperliquid.xyz/info"
REQUEST_TIMEOUT_SECS = 10

RawFetcher = Callable[[dict[str, Any]], Any]


def default_hyperliquid_fetcher(body: dict[str, Any]) -> Any:
    """Default `RawFetcher`: POST `body` as JSON to the info endpoint and
    return the parsed response body unchanged (its shape depends on
    `body["type"]` - callers unpack it, this stays a thin transport)."""
    request = urllib.request.Request(
        HYPERLIQUID_INFO_URL,
        data=json.dumps(body).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=REQUEST_TIMEOUT_SECS) as resp:
        return json.loads(resp.read())


class HyperliquidInfoClient:
    """Read-only wrapper over the four `/info` request types this project
    uses. No signed/authenticated requests exist here - Hyperliquid's
    `/info` endpoint is entirely public."""

    def __init__(self, fetcher: RawFetcher | None = None) -> None:
        self._fetch = fetcher or default_hyperliquid_fetcher

    def get_meta_and_asset_ctxs(self) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        """Returns `(universe, asset_ctxs)`, index-aligned by coin."""
        body = self._fetch({"type": "metaAndAssetCtxs"})
        if (
            not isinstance(body, list)
            or len(body) != 2
            or not isinstance(body[0], dict)
            or "universe" not in body[0]
            or not isinstance(body[1], list)
        ):
            raise RuntimeError(f"unexpected metaAndAssetCtxs response shape: {body!r}")
        universe = body[0]["universe"]
        asset_ctxs = body[1]
        if len(universe) != len(asset_ctxs):
            raise RuntimeError("metaAndAssetCtxs universe/asset_ctxs length mismatch")
        return universe, asset_ctxs

    def get_funding_history(
        self, coin: str, *, start_time_ms: int, end_time_ms: int | None = None
    ) -> list[dict[str, Any]]:
        body: dict[str, Any] = {
            "type": "fundingHistory",
            "coin": coin,
            "startTime": start_time_ms,
        }
        if end_time_ms is not None:
            body["endTime"] = end_time_ms
        result = self._fetch(body)
        if not isinstance(result, list):
            raise RuntimeError(f"unexpected fundingHistory response shape: {result!r}")
        return result

    def get_predicted_fundings(self) -> list[list[Any]]:
        """All coins in one call - callers filter to their own universe."""
        result = self._fetch({"type": "predictedFundings"})
        if not isinstance(result, list):
            raise RuntimeError(f"unexpected predictedFundings response shape: {result!r}")
        return result

    def get_l2_book(self, coin: str) -> dict[str, Any]:
        result = self._fetch({"type": "l2Book", "coin": coin})
        if not isinstance(result, dict) or "levels" not in result:
            raise RuntimeError(f"unexpected l2Book response shape: {result!r}")
        return result
