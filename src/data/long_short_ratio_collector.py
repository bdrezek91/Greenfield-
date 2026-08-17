"""Live poller for Bybit's long/short account-ratio endpoint - the
poll-based counterpart to src/data/microstructure_collector.py's
WebSocket-based collector.

This exists purely because the endpoint has no backfill (see
src/data/long_short_ratio_client.py's module docstring): "5min" ratio
readings from before this collector was started are gone forever, exactly
the situation microstructure order-book/trade data was already in - so
this follows the same "start collecting now, worry about enough history
later" shape, just REST-polled instead of WebSocket-pushed.

PARTIALLY VERIFIED LIVE: NOT VERIFIED IN THIS SESSION - see
src/data/long_short_ratio_client.py's module docstring for the network
egress limitation. Validate on the VPS before relying on this.
"""

from __future__ import annotations

import signal
import time
from collections.abc import Callable
from pathlib import Path

import pandas as pd
import structlog

from src.data.ingest_long_short_ratio import parse_long_short_ratio_rows
from src.data.long_short_ratio_client import BybitLongShortRatioClient
from src.data.storage import write_long_short_ratio

log = structlog.get_logger()


def _raise_keyboard_interrupt(signum: int, frame: object) -> None:
    raise KeyboardInterrupt


class LongShortRatioCollector:
    def __init__(
        self,
        symbol: str,
        data_dir: Path,
        *,
        category: str = "linear",
        period: str = "5min",
        poll_interval_secs: float = 60.0,
        client: BybitLongShortRatioClient | None = None,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self._symbol = symbol
        self._data_dir = Path(data_dir)
        self._category = category
        self._period = period
        self._poll_interval_secs = poll_interval_secs
        self._client = client or BybitLongShortRatioClient()
        self._clock = clock
        self._sleep = sleep
        # De-dup across polls: Bybit re-returns the same recent readings
        # every call until a new period rolls over, so only rows newer
        # than the last one seen get written - never rewriting a partition
        # that was already flushed.
        self._last_written_ts: pd.Timestamp | None = None

    def poll_once(self) -> int:
        """Fetch the current snapshot, write any rows newer than the last
        one already written. Returns the number of new rows written.
        """
        raw_rows = self._client.get_long_short_ratio(
            category=self._category, symbol=self._symbol, period=self._period
        )
        df = parse_long_short_ratio_rows(raw_rows, self._symbol)
        if df.empty:
            return 0
        if self._last_written_ts is not None:
            df = df[df["timestamp"] > self._last_written_ts]
        if df.empty:
            return 0
        write_long_short_ratio(df, self._data_dir, self._period)
        self._last_written_ts = df["timestamp"].max()
        return len(df)

    def run_forever(self) -> None:
        """Poll every `poll_interval_secs` until SIGINT/SIGTERM - same
        graceful-shutdown handling as MicrostructureCollector.run_forever
        (SIGTERM does not raise KeyboardInterrupt on its own, so a bare
        `except KeyboardInterrupt` would miss `docker stop`)."""
        signal.signal(signal.SIGTERM, _raise_keyboard_interrupt)
        log.info(
            "long/short ratio collector starting",
            symbol=self._symbol,
            period=self._period,
            poll_interval_secs=self._poll_interval_secs,
        )
        try:
            while True:
                try:
                    n = self.poll_once()
                    if n:
                        log.info("long/short ratio poll", symbol=self._symbol, new_rows=n)
                except Exception as exc:  # noqa: BLE001 - one bad poll must not kill the loop
                    log.error("long/short ratio poll failed", error=str(exc))
                self._sleep(self._poll_interval_secs)
        except KeyboardInterrupt:
            log.info("long/short ratio collector stopping")
