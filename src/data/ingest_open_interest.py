"""Fetch Bybit open-interest history for a date range - the open-interest
counterpart to src/data/ingest.py.

Unlike kline/funding-rate-history, this endpoint is cursor-paginated
(`nextPageCursor`), not time-window paginated - we page forward through
cursors within the requested half-open range until Bybit stops returning one.
"""

from __future__ import annotations

import pandas as pd

from src.data.open_interest_client import MAX_LIMIT, BybitOpenInterestClient
from src.data.schema_funding import OPEN_INTEREST_COLUMNS, empty_open_interest_frame

# Hard ceiling so a misconfigured range/API can never loop forever.
MAX_PAGES = 5000


def _parse_page(rows: list[dict[str, str]], symbol: str) -> pd.DataFrame:
    if not rows:
        return empty_open_interest_frame()
    df = pd.DataFrame(rows)
    df["timestamp"] = pd.to_datetime(df["timestamp"].astype("int64"), unit="ms", utc=True)
    df["open_interest"] = df["openInterest"].astype("float64")
    df["symbol"] = symbol
    return df[list(OPEN_INTEREST_COLUMNS)]


def fetch_open_interest(
    client: BybitOpenInterestClient,
    *,
    category: str,
    symbol: str,
    interval_time: str,
    start_ms: int,
    end_ms: int,
) -> pd.DataFrame:
    """Fetch and assemble all open-interest records for `symbol` in
    the half-open range ``[start_ms, end_ms)``.
    """
    if start_ms > end_ms:
        raise ValueError("start_ms must be <= end_ms")

    pages: list[pd.DataFrame] = []
    cursor: str | None = None

    for _ in range(MAX_PAGES):
        rows, cursor = client.get_open_interest_page(
            category=category,
            symbol=symbol,
            interval_time=interval_time,
            start_ms=start_ms,
            end_ms=end_ms,
            limit=MAX_LIMIT,
            cursor=cursor,
        )
        if rows:
            pages.append(_parse_page(rows, symbol))
        if not cursor:
            break

    if not pages:
        return empty_open_interest_frame()

    combined = pd.concat(pages, ignore_index=True)
    combined = combined.drop_duplicates(subset=["timestamp", "symbol"])
    combined = combined[
        (combined["timestamp"] >= pd.Timestamp(start_ms, unit="ms", tz="UTC"))
        & (combined["timestamp"] < pd.Timestamp(end_ms, unit="ms", tz="UTC"))
    ]
    combined = combined.sort_values("timestamp").reset_index(drop=True)
    return combined
