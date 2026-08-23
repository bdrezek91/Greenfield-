"""Live pollers for Binance's open-interest-history and global
long/short-account-ratio endpoints - the Binance counterpart to
src/data/long_short_ratio_collector.py.

Both Binance statistics endpoints only retain ~30 days of history (see
src/data/binance_derivatives_client.py's module docstring), so - like
Bybit's long/short poller - this follows a "start collecting now" shape:
readings older than 30 days before this collector was started are gone
for good once that window rolls past.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pandas as pd

from src.data.binance_derivatives_client import (
    BinanceLongShortRatioClient,
    BinanceOpenInterestClient,
)
from src.data.binance_derivatives_storage import (
    write_binance_long_short_ratio,
    write_binance_open_interest,
)
from src.data.rest_poller import run_polling_loop
from src.data.schema_binance_derivatives import (
    BINANCE_LONG_SHORT_RATIO_COLUMNS,
    BINANCE_OPEN_INTEREST_COLUMNS,
    empty_binance_long_short_ratio_frame,
    empty_binance_open_interest_frame,
)


def _parse_open_interest_rows(rows: list[dict[str, Any]], symbol: str) -> pd.DataFrame:
    if not rows:
        return empty_binance_open_interest_frame()
    df = pd.DataFrame(rows)
    df["timestamp"] = pd.to_datetime(df["timestamp"].astype("int64"), unit="ms", utc=True)
    df["open_interest"] = df["sumOpenInterest"].astype("float64")
    df["open_interest_value"] = df["sumOpenInterestValue"].astype("float64")
    df["symbol"] = symbol
    df = df.drop_duplicates(subset=["timestamp", "symbol"]).sort_values("timestamp")
    return df[list(BINANCE_OPEN_INTEREST_COLUMNS)].reset_index(drop=True)


def _parse_long_short_ratio_rows(rows: list[dict[str, Any]], symbol: str) -> pd.DataFrame:
    if not rows:
        return empty_binance_long_short_ratio_frame()
    df = pd.DataFrame(rows)
    df["timestamp"] = pd.to_datetime(df["timestamp"].astype("int64"), unit="ms", utc=True)
    df["long_account"] = df["longAccount"].astype("float64")
    df["short_account"] = df["shortAccount"].astype("float64")
    df["long_short_ratio"] = df["longShortRatio"].astype("float64")
    df["symbol"] = symbol
    df = df.drop_duplicates(subset=["timestamp", "symbol"]).sort_values("timestamp")
    return df[list(BINANCE_LONG_SHORT_RATIO_COLUMNS)].reset_index(drop=True)


class BinanceOpenInterestCollector:
    def __init__(
        self,
        symbol: str,
        data_dir: Path,
        *,
        period: str = "5m",
        poll_interval_secs: float = 60.0,
        client: BinanceOpenInterestClient | None = None,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self._symbol = symbol
        self._data_dir = Path(data_dir)
        self._period = period
        self._poll_interval_secs = poll_interval_secs
        self._client = client or BinanceOpenInterestClient()
        self._clock = clock
        self._sleep = sleep
        # De-dup across polls: only rows newer than the last one already
        # written get flushed, never rewriting an already-flushed partition.
        self._last_written_ts: pd.Timestamp | None = None

    def poll_once(self) -> int:
        raw_rows = self._client.get_open_interest_history(self._symbol, self._period)
        df = _parse_open_interest_rows(raw_rows, self._symbol)
        if df.empty:
            return 0
        if self._last_written_ts is not None:
            df = df[df["timestamp"] > self._last_written_ts]
        if df.empty:
            return 0
        write_binance_open_interest(df, self._data_dir, self._period)
        self._last_written_ts = df["timestamp"].max()
        return len(df)

    def run_forever(self) -> None:
        run_polling_loop(
            name="binance open-interest",
            poll_once=self.poll_once,
            poll_interval_secs=self._poll_interval_secs,
            sleep=self._sleep,
            extra_log_fields={"symbol": self._symbol, "period": self._period},
        )


class BinanceLongShortRatioCollector:
    def __init__(
        self,
        symbol: str,
        data_dir: Path,
        *,
        period: str = "5m",
        poll_interval_secs: float = 60.0,
        client: BinanceLongShortRatioClient | None = None,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self._symbol = symbol
        self._data_dir = Path(data_dir)
        self._period = period
        self._poll_interval_secs = poll_interval_secs
        self._client = client or BinanceLongShortRatioClient()
        self._clock = clock
        self._sleep = sleep
        self._last_written_ts: pd.Timestamp | None = None

    def poll_once(self) -> int:
        raw_rows = self._client.get_long_short_ratio_history(self._symbol, self._period)
        df = _parse_long_short_ratio_rows(raw_rows, self._symbol)
        if df.empty:
            return 0
        if self._last_written_ts is not None:
            df = df[df["timestamp"] > self._last_written_ts]
        if df.empty:
            return 0
        write_binance_long_short_ratio(df, self._data_dir, self._period)
        self._last_written_ts = df["timestamp"].max()
        return len(df)

    def run_forever(self) -> None:
        run_polling_loop(
            name="binance long/short ratio",
            poll_once=self.poll_once,
            poll_interval_secs=self._poll_interval_secs,
            sleep=self._sleep,
            extra_log_fields={"symbol": self._symbol, "period": self._period},
        )
