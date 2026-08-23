"""Fetch OKX klines for a date range and assemble them into the canonical
schema (src.data.schema) - the OKX counterpart to src/data/ingest.py.

OKX's `history-candles` pages BACKWARD via an `after` cursor ("give me
candles strictly older than this timestamp") - the same backward
direction as Bybit's `end`-based paging (see src/data/ingest.py), unlike
Binance's forward pagination (src/data/ingest_binance_klines.py). Unlike
Bybit's cursor, `after` is exclusive and singular (no separate
"newest boundary" parameter), so the first page's cursor is nudged one
step past `end_ms` to include a candle exactly at `end_ms`.

Only `confirm == "1"` (fully closed) candles are kept - `confirm == "0"`
marks a candle still forming, which must never be treated as a completed
historical bar.
"""

from __future__ import annotations

import pandas as pd

from src.data.config import TIMEFRAME_MS
from src.data.okx_klines_client import MAX_LIMIT, OkxKlineClient
from src.data.schema import COLUMNS, empty_klines_frame

# Hard ceiling so a misconfigured range can never loop forever against a
# live (or misbehaving mock) API.
MAX_PAGES = 5000


def _parse_page(rows: list[list], symbol: str, timeframe: str) -> pd.DataFrame:
    confirmed = [row for row in rows if str(row[8]) == "1"]
    if not confirmed:
        return empty_klines_frame()
    df = pd.DataFrame(
        confirmed,
        columns=[
            "timestamp",
            "open",
            "high",
            "low",
            "close",
            "vol",
            "volCcy",
            "volCcyQuote",
            "confirm",
        ],
    )
    df["timestamp"] = pd.to_datetime(df["timestamp"].astype("int64"), unit="ms", utc=True)
    for col in ("open", "high", "low", "close"):
        df[col] = df[col].astype("float64")
    # OKX swaps are contract-denominated ("vol" is contracts, not base
    # currency - see configs/instruments_okx.yaml) - volCcy/volCcyQuote
    # are already in base/quote currency, matching Bybit/Binance's
    # volume/turnover semantics.
    df["volume"] = df["volCcy"].astype("float64")
    df["turnover"] = df["volCcyQuote"].astype("float64")
    df["symbol"] = symbol
    df["timeframe"] = timeframe
    return df[list(COLUMNS)]


def fetch_okx_klines(
    client: OkxKlineClient,
    *,
    inst_id: str,
    bar: str,
    timeframe: str,
    start_ms: int,
    end_ms: int,
) -> pd.DataFrame:
    """Fetch and assemble all candles for `inst_id`/`timeframe` in [start_ms, end_ms]."""
    if start_ms > end_ms:
        raise ValueError("start_ms must be <= end_ms")

    step_ms = TIMEFRAME_MS[timeframe]
    pages: list[pd.DataFrame] = []
    cursor_after = end_ms + step_ms  # "after" is exclusive - nudge to include end_ms itself

    for _ in range(MAX_PAGES):
        rows = client.get_kline_page(inst_id, bar, after_ms=cursor_after, limit=MAX_LIMIT)
        if not rows:
            break

        page = _parse_page(rows, inst_id, timeframe)
        raw_oldest_ms = min(int(row[0]) for row in rows)
        if not page.empty:
            pages.append(page)

        if raw_oldest_ms <= start_ms or len(rows) < MAX_LIMIT:
            break
        cursor_after = raw_oldest_ms

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
