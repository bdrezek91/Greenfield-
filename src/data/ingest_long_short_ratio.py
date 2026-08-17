"""Parse Bybit long/short account-ratio API rows into the canonical
schema (src/data/schema_long_short_ratio.py) - the long/short-ratio
counterpart to src/data/ingest_open_interest.py's `_parse_page`.

No range-fetch/pagination helper here (unlike ingest_open_interest.py):
this endpoint has none to page through - see
src/data/long_short_ratio_client.py's module docstring. A caller (the
long-running poller, scripts/collect_long_short_ratio.py) calls
`parse_long_short_ratio_rows` on each poll's raw response and appends the
result.
"""

from __future__ import annotations

import pandas as pd

from src.data.schema_long_short_ratio import LONG_SHORT_RATIO_COLUMNS, empty_long_short_ratio_frame


def parse_long_short_ratio_rows(rows: list[dict[str, str]], symbol: str) -> pd.DataFrame:
    if not rows:
        return empty_long_short_ratio_frame()
    df = pd.DataFrame(rows)
    df["timestamp"] = pd.to_datetime(df["timestamp"].astype("int64"), unit="ms", utc=True)
    df["buy_ratio"] = df["buyRatio"].astype("float64")
    df["sell_ratio"] = df["sellRatio"].astype("float64")
    df["symbol"] = symbol
    df = df.drop_duplicates(subset=["timestamp", "symbol"]).sort_values("timestamp")
    return df[list(LONG_SHORT_RATIO_COLUMNS)].reset_index(drop=True)
