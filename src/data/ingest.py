"""Fetch Kraken Futures klines for a date range and assemble them into the
canonical schema.

Kraken/ccxt's OHLC endpoint pages FORWARD from a `since` timestamp (the
opposite of Bybit's newest-first, page-backward-from-`end` convention this
module used before the Phase-15+ exchange migration - see
docs/PROJECT_STATUS.md): each page starts at `start_ms` and returns up to
`limit` candles moving forward in time; we advance `start_ms` to just past
the newest candle received until we reach `end_ms` or a page comes back
short (meaning we've hit the end of available history).
"""

from __future__ import annotations

import pandas as pd

from src.data.config import TIMEFRAME_MS
from src.data.kraken_client import MAX_LIMIT, KrakenKlineClient
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
    client: KrakenKlineClient,
    *,
    symbol: str,
    interval: str,
    timeframe: str,
    start_ms: int,
    end_ms: int,
) -> pd.DataFrame:
    """Fetch and assemble all candles for `symbol`/`timeframe` in [start_ms, end_ms]."""
    if start_ms > end_ms:
        raise ValueError("start_ms must be <= end_ms")

    step_ms = TIMEFRAME_MS[timeframe]
    pages: list[pd.DataFrame] = []
    cursor_start = start_ms

    for _ in range(MAX_PAGES):
        rows = client.get_kline_page(
            symbol=symbol,
            interval=interval,
            start_ms=cursor_start,
            end_ms=end_ms,
            limit=MAX_LIMIT,
        )
        if not rows:
            break

        page = _parse_page(rows, symbol, timeframe)
        pages.append(page)

        newest_ts_ms = int(page["timestamp"].max().value // 1_000_000)
        if newest_ts_ms >= end_ms or len(rows) < MAX_LIMIT:
            break
        cursor_start = newest_ts_ms + step_ms

    if not pages:
        return empty_klines_frame()

    combined = pd.concat(pages, ignore_index=True)
    combined = combined.drop_duplicates(subset=["timestamp", "symbol", "timeframe"])
    combined = combined[
        (combined["timestamp"] >= pd.Timestamp(start_ms, unit="ms", tz="UTC"))
        & (combined["timestamp"] <= pd.Timestamp(end_ms, unit="ms", tz="UTC"))
    ]
    combined = combined.sort_values("timestamp").reset_index(drop=True)
    return combined
