"""Live poller for Deribit's per-currency market summary snapshot - the
Deribit counterpart to src/data/binance_derivatives_collector.py /
src/data/okx_derivatives_collector.py, sharing the same
src/data/rest_poller.py loop.

Unlike those pollers (dedup by "only rows newer than the last timestamp
seen"), every poll here is a complete, independently-timestamped snapshot
of every active instrument for one currency+kind - there is nothing to
compare against a previous poll, so every successful poll writes its full
batch (storage's own (timestamp, instrument_name) dedup makes a re-run of
the exact same poll a no-op, not a duplicate).
"""

from __future__ import annotations

import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pandas as pd

from src.data.deribit_market_summary_client import DeribitMarketSummaryClient
from src.data.deribit_market_summary_storage import write_deribit_market_summary
from src.data.rest_poller import run_polling_loop
from src.data.schema_deribit_market_summary import (
    DERIBIT_MARKET_SUMMARY_COLUMNS,
    empty_deribit_market_summary_frame,
)


def _parse_rows(rows: list[dict[str, Any]], poll_time: pd.Timestamp, kind: str) -> pd.DataFrame:
    if not rows:
        return empty_deribit_market_summary_frame()
    df = pd.DataFrame(rows)
    df["timestamp"] = poll_time
    df["kind"] = kind
    df["last_price"] = df["last"] if "last" in df.columns else None
    for col in (
        "bid_price",
        "ask_price",
        "mark_price",
        "mid_price",
        "last_price",
        "open_interest",
        "volume",
        "volume_usd",
        "mark_iv",
        "underlying_price",
    ):
        if col not in df.columns:
            df[col] = None
        df[col] = pd.to_numeric(df[col], errors="coerce")
    if "underlying_index" not in df.columns:
        df["underlying_index"] = None
    df["instrument_name"] = df["instrument_name"].astype("string")
    df["base_currency"] = df["base_currency"].astype("string")
    df["underlying_index"] = df["underlying_index"].astype("string")
    df = df.drop_duplicates(subset=["instrument_name"]).sort_values("instrument_name")
    return df[list(DERIBIT_MARKET_SUMMARY_COLUMNS)].reset_index(drop=True)


class DeribitMarketSummaryCollector:
    def __init__(
        self,
        currency: str,
        kind: str,
        data_dir: Path,
        *,
        poll_interval_secs: float = 300.0,
        client: DeribitMarketSummaryClient | None = None,
        clock: Callable[[], pd.Timestamp] = lambda: pd.Timestamp.now(tz="UTC"),
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self._currency = currency
        self._kind = kind
        self._data_dir = Path(data_dir)
        self._poll_interval_secs = poll_interval_secs
        self._client = client or DeribitMarketSummaryClient()
        self._clock = clock
        self._sleep = sleep

    def poll_once(self) -> int:
        raw_rows = self._client.get_book_summary_by_currency(self._currency, self._kind)
        df = _parse_rows(raw_rows, self._clock(), self._kind)
        if df.empty:
            return 0
        write_deribit_market_summary(df, self._data_dir, self._currency, self._kind)
        return len(df)

    def run_forever(self) -> None:
        run_polling_loop(
            name="deribit market-summary",
            poll_once=self.poll_once,
            poll_interval_secs=self._poll_interval_secs,
            sleep=self._sleep,
            extra_log_fields={"currency": self._currency, "kind": self._kind},
        )
