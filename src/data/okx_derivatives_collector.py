"""Live pollers for OKX's open-interest snapshot and long/short
account-ratio endpoints - the OKX counterpart to
src/data/binance_derivatives_collector.py.

open-interest has no time-window backfill (a single current snapshot per
poll, like Bybit's long/short poller); long-short-account-ratio-contract
does return history but OKX's own retention window applies - see
src/data/okx_derivatives_client.py's module docstring. Both follow the
same "start collecting now" shape as every other REST poller in this
project.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pandas as pd

from src.data.okx_derivatives_client import OkxLongShortRatioClient, OkxOpenInterestClient
from src.data.okx_derivatives_storage import (
    write_okx_long_short_ratio,
    write_okx_open_interest,
)
from src.data.rest_poller import run_polling_loop
from src.data.schema_okx_derivatives import (
    OKX_LONG_SHORT_RATIO_COLUMNS,
    OKX_OPEN_INTEREST_COLUMNS,
    empty_okx_long_short_ratio_frame,
    empty_okx_open_interest_frame,
)


def _parse_open_interest_rows(rows: list[dict[str, Any]], inst_id: str) -> pd.DataFrame:
    if not rows:
        return empty_okx_open_interest_frame()
    df = pd.DataFrame(rows)
    df["timestamp"] = pd.to_datetime(df["ts"].astype("int64"), unit="ms", utc=True)
    df["open_interest"] = df["oi"].astype("float64")
    df["open_interest_ccy"] = df["oiCcy"].astype("float64")
    df["open_interest_usd"] = df["oiUsd"].astype("float64")
    df["inst_id"] = inst_id
    df = df.drop_duplicates(subset=["timestamp", "inst_id"]).sort_values("timestamp")
    return df[list(OKX_OPEN_INTEREST_COLUMNS)].reset_index(drop=True)


def _parse_long_short_ratio_rows(rows: list[list[str]], inst_id: str) -> pd.DataFrame:
    """OKX's long/short-ratio rows are `[timestamp_str, ratio_str]` pairs,
    not objects like every other client in this project - see
    src/data/schema_okx_derivatives.py's module docstring for why.
    """
    if not rows:
        return empty_okx_long_short_ratio_frame()
    df = pd.DataFrame(rows, columns=["ts", "ratio"])
    df["timestamp"] = pd.to_datetime(df["ts"].astype("int64"), unit="ms", utc=True)
    df["long_short_ratio"] = df["ratio"].astype("float64")
    df["inst_id"] = inst_id
    df = df.drop_duplicates(subset=["timestamp", "inst_id"]).sort_values("timestamp")
    return df[list(OKX_LONG_SHORT_RATIO_COLUMNS)].reset_index(drop=True)


class OkxOpenInterestCollector:
    def __init__(
        self,
        inst_id: str,
        data_dir: Path,
        *,
        poll_interval_secs: float = 60.0,
        client: OkxOpenInterestClient | None = None,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self._inst_id = inst_id
        self._data_dir = Path(data_dir)
        self._poll_interval_secs = poll_interval_secs
        self._client = client or OkxOpenInterestClient()
        self._clock = clock
        self._sleep = sleep
        self._last_written_ts: pd.Timestamp | None = None

    def poll_once(self) -> int:
        raw_rows = self._client.get_open_interest_snapshot(self._inst_id)
        df = _parse_open_interest_rows(raw_rows, self._inst_id)
        if df.empty:
            return 0
        if self._last_written_ts is not None:
            df = df[df["timestamp"] > self._last_written_ts]
        if df.empty:
            return 0
        write_okx_open_interest(df, self._data_dir)
        self._last_written_ts = df["timestamp"].max()
        return len(df)

    def run_forever(self) -> None:
        run_polling_loop(
            name="okx open-interest",
            poll_once=self.poll_once,
            poll_interval_secs=self._poll_interval_secs,
            sleep=self._sleep,
            extra_log_fields={"inst_id": self._inst_id},
        )


class OkxLongShortRatioCollector:
    def __init__(
        self,
        inst_id: str,
        data_dir: Path,
        *,
        period: str = "5m",
        poll_interval_secs: float = 60.0,
        client: OkxLongShortRatioClient | None = None,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self._inst_id = inst_id
        self._data_dir = Path(data_dir)
        self._period = period
        self._poll_interval_secs = poll_interval_secs
        self._client = client or OkxLongShortRatioClient()
        self._clock = clock
        self._sleep = sleep
        self._last_written_ts: pd.Timestamp | None = None

    def poll_once(self) -> int:
        raw_rows = self._client.get_long_short_ratio_history(self._inst_id, self._period)
        df = _parse_long_short_ratio_rows(raw_rows, self._inst_id)
        if df.empty:
            return 0
        if self._last_written_ts is not None:
            df = df[df["timestamp"] > self._last_written_ts]
        if df.empty:
            return 0
        write_okx_long_short_ratio(df, self._data_dir, self._period)
        self._last_written_ts = df["timestamp"].max()
        return len(df)

    def run_forever(self) -> None:
        run_polling_loop(
            name="okx long/short ratio",
            poll_once=self.poll_once,
            poll_interval_secs=self._poll_interval_secs,
            sleep=self._sleep,
            extra_log_fields={"inst_id": self._inst_id, "period": self._period},
        )
