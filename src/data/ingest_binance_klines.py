"""Fetch Binance klines for a date range and assemble them into the
canonical schema (src.data.schema) - the Binance counterpart to
src/data/ingest.py.

Binance's `/fapi/v1/klines` pages FORWARD from `startTime` (ascending,
oldest-first, capped at `limit`), unlike Bybit's `/v5/market/kline`, which
pages backward from `end` (newest-first) - see src/data/bybit_client.py's
usage in ingest.py for the opposite convention. We page forward, advancing
`start_ms` past the last candle returned each time.
"""

from __future__ import annotations

import pandas as pd

from src.data.binance_klines_client import MAX_LIMIT, BinanceKlineClient
from src.data.config import TIMEFRAME_MS
from src.data.schema import COLUMNS, empty_klines_frame

# Hard ceiling so a misconfigured range can never loop forever against a
# live (or misbehaving mock) API.
MAX_PAGES = 5000


def _parse_page(rows: list[list], symbol: str, timeframe: str) -> pd.DataFrame:
    if not rows:
        return empty_klines_frame()
    df = pd.DataFrame(
        [row[:6] for row in rows],
        columns=["timestamp", "open", "high", "low", "close", "volume"],
    )
    df["timestamp"] = pd.to_datetime(df["timestamp"].astype("int64"), unit="ms", utc=True)
    for col in ("open", "high", "low", "close", "volume"):
        df[col] = df[col].astype("float64")
    # Binance's kline response has no separate quote-turnover field in the
    # first 6 elements we keep - quote_volume (index 7) is the equivalent
    # of Bybit's "turnover", included for schema compatibility rather than
    # silently dropped.
    df["turnover"] = [float(row[7]) for row in rows]
    df["symbol"] = symbol
    df["timeframe"] = timeframe
    return df[list(COLUMNS)]


def fetch_binance_klines(
    client: BinanceKlineClient,
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
