"""Live collector for Bybit's public order book, trade tape, and
liquidation WebSocket streams, buffering and periodically flushing to
Parquet via src/data/microstructure_writer.py.

PARTIALLY VERIFIED LIVE (on the VPS - this session's own network egress
policy still blocks api.bybit.com): `orderbook_stream`/`trade_stream`
subscribed without error. `liquidation_stream` did not - pybit has removed
it in favor of `all_liquidation_stream`, now used here - but the batched
message shape parse_liquidation_messages() assumes has NOT yet been seen
on a real message (no liquidations occurred during that run); treat that
one shape as still unconfirmed until the first real batch arrives.

Unlike the paper-trading node (Phase 14), there is no "safe to fail
silently" concern here: this only ever reads public market data and writes
to local Parquet, no account/order actions are involved regardless of
TRADING_MODE.
"""

from __future__ import annotations

import signal
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

import structlog

from src.data.microstructure_parser import (
    apply_orderbook_message,
    parse_liquidation_messages,
    parse_trade_message,
)
from src.data.microstructure_writer import write_batch
from src.data.orderbook_state import OrderBookState

log = structlog.get_logger()


class MicrostructureCollector:
    _STREAMS: tuple[str, ...] = ("orderbook", "trades", "liquidations")

    def __init__(
        self,
        symbol: str,
        data_dir: Path,
        *,
        flush_interval_secs: float = 30.0,
        top_n: int = 10,
        ws_factory: Callable[[], Any] | None = None,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._symbol = symbol
        self._data_dir = Path(data_dir)
        self._flush_interval_secs = flush_interval_secs
        self._book_state = OrderBookState(top_n=top_n)
        self._clock = clock
        self._buffers: dict[str, list[dict]] = {s: [] for s in self._STREAMS}
        now = clock()
        self._last_flush: dict[str, float] = dict.fromkeys(self._STREAMS, now)
        self._ws_factory = ws_factory or self._default_ws_factory

    @staticmethod
    def _default_ws_factory() -> Any:
        from pybit.unified_trading import WebSocket

        return WebSocket(testnet=False, channel_type="linear")

    def on_orderbook_message(self, message: dict) -> None:
        row = apply_orderbook_message(self._book_state, message)
        if row is not None:
            self._buffers["orderbook"].append(row)
        self._maybe_flush("orderbook")

    def on_trade_message(self, message: dict) -> None:
        self._buffers["trades"].extend(parse_trade_message(message))
        self._maybe_flush("trades")

    def on_liquidation_message(self, message: dict) -> None:
        self._buffers["liquidations"].extend(parse_liquidation_messages(message))
        self._maybe_flush("liquidations")

    def _maybe_flush(self, stream: str) -> None:
        if self._clock() - self._last_flush[stream] >= self._flush_interval_secs:
            self.flush(stream)

    def flush(self, stream: str | None = None) -> None:
        """Write out (and clear) whichever streams' buffers are due, or a
        single named stream. Safe to call with empty buffers (no-op).
        """
        streams = [stream] if stream else list(self._STREAMS)
        for s in streams:
            rows, self._buffers[s] = self._buffers[s], []
            self._last_flush[s] = self._clock()
            if rows:
                path = write_batch(rows, self._data_dir, s, self._symbol)
                log.info("flushed microstructure batch", stream=s, rows=len(rows), path=str(path))

    def run_forever(self) -> None:
        """Subscribe to all three public streams for `self._symbol` and
        block, flushing buffers as their interval elapses. Ctrl+C (SIGINT)
        or `docker stop`/`kill` (SIGTERM) both trigger a final flush before
        exit - Python does NOT do this for SIGTERM by default (only
        SIGINT raises KeyboardInterrupt on its own), so a bare `except
        KeyboardInterrupt` here would silently lose whatever was buffered
        but not yet flushed on every `docker stop`, the normal way this
        long-running collector gets stopped/restarted.
        """
        signal.signal(signal.SIGTERM, _raise_keyboard_interrupt)

        ws = self._ws_factory()
        ws.orderbook_stream(50, self._symbol, self.on_orderbook_message)
        ws.trade_stream(self._symbol, self.on_trade_message)
        # ws.liquidation_stream() is gone (confirmed live: "handler not
        # found" - Bybit deprecated the single-object liquidation topic).
        ws.all_liquidation_stream(self._symbol, self.on_liquidation_message)
        log.info(
            "microstructure collector subscribed",
            symbol=self._symbol,
            flush_interval_secs=self._flush_interval_secs,
        )
        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            pass
        finally:
            log.info("microstructure collector stopping, flushing remaining buffers")
            self.flush()


def _raise_keyboard_interrupt(signum: int, frame: object) -> None:
    raise KeyboardInterrupt
