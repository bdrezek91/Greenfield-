"""Fetch Bybit funding-rate history for a date range - the funding-rate
counterpart to src/data/ingest.py.

Bybit returns pages of at most `MAX_LIMIT` records, newest-first, ending at
a given `end` timestamp (same pagination shape as kline) - we page
backwards from `end_ms` towards `start_ms`.
"""

from __future__ import annotations

import pandas as pd

from src.data.funding_client import MAX_LIMIT, BybitFundingClient
from src.data.schema_funding import FUNDING_COLUMNS, empty_funding_frame

# Hard ceiling so a misconfigured range can never loop forever against a
# live (or misbehaving mock) API. Funding settles every 8h -> ~3/day, so
# this comfortably covers many years even at MAX_LIMIT=200/page.
MAX_PAGES = 5000


def _parse_page(rows: list[dict[str, str]], symbol: str) -> pd.DataFrame:
    if not rows:
        return empty_funding_frame()
    df = pd.DataFrame(rows)
    df["timestamp"] = pd.to_datetime(
        df["fundingRateTimestamp"].astype("int64"), unit="ms", utc=True
    )
    df["funding_rate"] = df["fundingRate"].astype("float64")
    df["symbol"] = symbol
    return df[list(FUNDING_COLUMNS)]


def fetch_funding_rates(
    client: BybitFundingClient,
    *,
    category: str,
    symbol: str,
    start_ms: int,
    end_ms: int,
) -> pd.DataFrame:
    """Fetch and assemble all funding-rate records for `symbol` in
    the half-open range ``[start_ms, end_ms)``.
    """
    if start_ms > end_ms:
        raise ValueError("start_ms must be <= end_ms")

    pages: list[pd.DataFrame] = []
    cursor_end = end_ms

    for _ in range(MAX_PAGES):
        rows = client.get_funding_rate_page(
            category=category,
            symbol=symbol,
            start_ms=start_ms,
            end_ms=cursor_end,
            limit=MAX_LIMIT,
        )
        if not rows:
            break

        page = _parse_page(rows, symbol)
        pages.append(page)

        oldest_ts_ms = int(page["timestamp"].min().value // 1_000_000)
        if oldest_ts_ms <= start_ms or len(rows) < MAX_LIMIT:
            break
        # Funding settles on fixed 8h boundaries - step back 1ms past the
        # oldest record seen so the next page doesn't re-fetch it.
        cursor_end = oldest_ts_ms - 1

    if not pages:
        return empty_funding_frame()

    combined = pd.concat(pages, ignore_index=True)
    combined = combined.drop_duplicates(subset=["timestamp", "symbol"])
    combined = combined[
        (combined["timestamp"] >= pd.Timestamp(start_ms, unit="ms", tz="UTC"))
        & (combined["timestamp"] < pd.Timestamp(end_ms, unit="ms", tz="UTC"))
    ]
    combined = combined.sort_values("timestamp").reset_index(drop=True)
    return combined
