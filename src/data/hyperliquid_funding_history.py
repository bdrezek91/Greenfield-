"""Paginated backfill of Hyperliquid's `fundingHistory` - the Hyperliquid
counterpart to src/data/ingest_funding.py.

Live-verified this session: a single `fundingHistory` call is capped at
500 rows and does NOT return everything in [startTime, endTime] - a
400-day request for BTC returned only ~21 days (hourly funding, 24/day).
Unlike Bybit's backward paging (src/data/ingest_funding.py), Hyperliquid's
`startTime` anchors the beginning of the window, so this pages FORWARD:
each page's last `time` + 1ms becomes the next page's `startTime`.
"""

from __future__ import annotations

import pandas as pd

from src.data.hyperliquid_client import HyperliquidInfoClient
from src.data.schema_hyperliquid import (
    HYPERLIQUID_FUNDING_HISTORY_COLUMNS,
    empty_hyperliquid_funding_history_frame,
)

# Hyperliquid settles funding hourly (~24/day) and caps each page at 500
# rows (~20.8 days/page) - this comfortably covers many years while
# guaranteeing a misconfigured range can never loop forever.
MAX_PAGES = 5000


def _parse_page(rows: list[dict[str, object]], coin: str) -> pd.DataFrame:
    if not rows:
        return empty_hyperliquid_funding_history_frame()
    df = pd.DataFrame(rows)
    df["timestamp"] = pd.to_datetime(df["time"].astype("int64"), unit="ms", utc=True)
    df["funding_rate"] = df["fundingRate"].astype("float64")
    df["premium"] = df["premium"].astype("float64")
    df["coin"] = coin
    return df[list(HYPERLIQUID_FUNDING_HISTORY_COLUMNS)]


def fetch_hyperliquid_funding_history(
    client: HyperliquidInfoClient,
    *,
    coin: str,
    start_ms: int,
    end_ms: int,
) -> pd.DataFrame:
    """Fetch and assemble all funding-history records for `coin` in
    [start_ms, end_ms]."""
    if start_ms > end_ms:
        raise ValueError("start_ms must be <= end_ms")

    pages: list[pd.DataFrame] = []
    cursor_start = start_ms
    seen_max_time: int | None = None

    for _ in range(MAX_PAGES):
        rows = client.get_funding_history(coin, start_time_ms=cursor_start, end_time_ms=end_ms)
        if not rows:
            break
        page = _parse_page(rows, coin)
        pages.append(page)
        page_max_time = int(page["timestamp"].max().value // 1_000_000)
        if seen_max_time is not None and page_max_time <= seen_max_time:
            # No forward progress - the API returned the same page again
            # rather than genuinely running out of history. Stop instead
            # of looping forever.
            break
        seen_max_time = page_max_time
        if page_max_time >= end_ms or len(rows) < 2:
            break
        cursor_start = page_max_time + 1

    if not pages:
        return empty_hyperliquid_funding_history_frame()
    combined = pd.concat(pages, ignore_index=True)
    combined = combined.drop_duplicates(subset=["timestamp", "coin"]).sort_values("timestamp")
    combined = combined[combined["timestamp"] <= pd.to_datetime(end_ms, unit="ms", utc=True)]
    return combined.reset_index(drop=True)
