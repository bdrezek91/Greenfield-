"""Fetch Bybit klines for a date range and assemble them into the canonical schema.

Bybit returns pages of at most `MAX_LIMIT` candles, newest-first, ending at a
given `end` timestamp. We page backwards from `end_ms` towards `start_ms`.
"""

from __future__ import annotations

import pandas as pd

from src.data.bybit_client import MAX_LIMIT, BybitKlineClient
from src.data.config import TIMEFRAME_MS
from src.data.schema import COLUMNS, empty_klines_frame

# Hard ceiling so a misconfigured range can never loop forever against a
# live (or misbehaving mock) API.
MAX_PAGES = 5000


def _parse_page(rows: list[list[str]], symbol: str, timeframe: str) -> pd.DataFrame:
    if not rows:
        return empty_klines_frame()
    df = pd.DataFrame(
        rows,
        columns=["timestamp", "open", "high", "low", "close", "volume", "turnover"],
    )
    df["timestamp"] = pd.to_datetime(df["timestamp"].astype("int64"), unit="ms", utc=True)
    for col in ("open", "high", "low", "close", "volume", "turnover"):
        df[col] = df[col].astype("float64")
    df["symbol"] = symbol
    df["timeframe"] = timeframe
    return df[list(COLUMNS)]


def fetch_klines(
    client: BybitKlineClient,
    *,
    category: str,
    symbol: str,
    interval: str,
    timeframe: str,
    start_ms: int,
    end_ms: int,
) -> pd.DataFrame:
    """Fetch and assemble candles in the half-open range ``[start_ms, end_ms)``."""
    if start_ms > end_ms:
        raise ValueError("start_ms must be <= end_ms")

    step_ms = TIMEFRAME_MS[timeframe]
    pages: list[pd.DataFrame] = []
    cursor_end = end_ms

    for _ in range(MAX_PAGES):
        rows = client.get_kline_page(
            category=category,
            symbol=symbol,
            interval=interval,
            start_ms=start_ms,
            end_ms=cursor_end,
            limit=MAX_LIMIT,
        )
        if not rows:
            break

        page = _parse_page(rows, symbol, timeframe)
        pages.append(page)

        oldest_ts_ms = int(page["timestamp"].min().value // 1_000_000)
        if oldest_ts_ms <= start_ms or len(rows) < MAX_LIMIT:
            break
        cursor_end = oldest_ts_ms - step_ms

    if not pages:
        return empty_klines_frame()

    combined = pd.concat(pages, ignore_index=True)
    combined = combined.drop_duplicates(subset=["timestamp", "symbol", "timeframe"])
    combined = combined[
        (combined["timestamp"] >= pd.Timestamp(start_ms, unit="ms", tz="UTC"))
        & (combined["timestamp"] < pd.Timestamp(end_ms, unit="ms", tz="UTC"))
    ]
    combined = combined.sort_values("timestamp").reset_index(drop=True)
    return combined
