"""Lossless, reconnecting Binance USDT-M Futures public WebSocket collector
(Cycle 10).

Structurally mirrors `src.data.okx_raw_collector.RawOkxCollector` - same
queue/writer/health/storage-reserve/signal-handling shape, proven in
Phase 1 - but is a fully independent module with its own connection,
symbols, and health files so a failure on one exchange's collector can
never affect another's (each is a separate isolated service; see
docker-compose.yml's `raw-binance-*` entries, disabled by default,
matching the `raw-okx-*`/`raw-coinbase-*` pattern from Cycles 7/9).

This collector wires the depth-continuity contract that already existed
in `src.data.binance_adapter` (`parse_binance_message`,
`BinanceDepthSequenceGate`) rather than reinventing it - that gate
correctly implements Binance's official REST-snapshot-bridge procedure
(`BinanceDepthSequenceGate.bootstrap`): the diff-depth stream alone is not
self-describing the way OKX's/Bybit's snapshot-in-stream design is, so a
`GET /fapi/v1/depth` REST snapshot's `lastUpdateId` must bootstrap each
symbol's gate before any stream event can be verified. This collector
fetches that snapshot right after subscribing, inside `_on_open` -
`WebSocketApp` dispatches `on_message` only after `on_open` returns, so
the blocking REST call cannot race incoming stream events on the same
connection; any events the OS already buffered during that call are
still processed in order afterward, and the gate's own "drop anything at
or before the snapshot's lastUpdateId" rule (`apply()` returning `False`
for a stale event, per the same official procedure) makes their exact
arrival timing irrelevant. If the snapshot fetch itself fails (network
error), that symbol's gate is simply left un-bootstrapped: its first
depth event then raises `BinanceSnapshotRequired` (fail-closed, forcing
the same reconnect-and-retry path as any other sequence anomaly) rather
than silently skipping verification.

Binance-specific differences from OKX otherwise: streams are subscribed
via `{"method": "SUBSCRIBE", "params": [<stream names>], "id": N}` on the
fixed `wss://fstream.binance.com/stream` endpoint (one stream name per
symbol per channel, e.g. `"btcusdt@trade"`) rather than per-channel
subscribe objects; keepalive is standard WebSocket protocol ping/pong via
`ws.run_forever(ping_interval=..., ping_timeout=...)` (Binance's
server-initiated ping/pong, matching Coinbase's transport-level keepalive)
rather than an application-level JSON ping message.

Channels captured: `trade` (-> "trades"), `depth@100ms` (-> "orderbook",
sequence-gated), `markPrice@1s` (-> "ticker", mark price/funding fields -
see `src.data.binance_normalized_event._ticker_records`), `forceOrder`
(-> "liquidations" - the public protocol does offer it; Cycle 14 added
the adapter channel mapping and normalizer support this collector's own
docstring had previously flagged as a gap, so liquidations now reach
Silver like every other channel here).

`symbols` are Binance-native (e.g. "BTCUSDT").
"""

from __future__ import annotations

import json
import queue
import re
import shutil
import signal
import threading
import time
import urllib.request
import uuid
from collections.abc import Callable
from pathlib import Path
from typing import Any

import structlog

from src.data.binance_adapter import (
    BinanceDepthSequenceGate,
    BinanceReplayError,
    parse_binance_message,
)
from src.data.collector_health import AtomicHealthPublisher, CollectorHealth
from src.data.raw_event import RawEventError, RawMarketEvent
from src.data.raw_store import AtomicRawWriter

log = structlog.get_logger()

BINANCE_FUTURES_WS = "wss://fstream.binance.com/stream"
BINANCE_DEPTH_SNAPSHOT_URL = "https://fapi.binance.com/fapi/v1/depth"
BINANCE_STREAM_SUFFIXES = ("trade", "depth@100ms", "markPrice@1s", "forceOrder")


def default_depth_snapshot_fetcher(symbol: str) -> int:
    """`GET /fapi/v1/depth` - public, unauthenticated market data. Returns
    `lastUpdateId` for `BinanceDepthSequenceGate.bootstrap`."""
    url = f"{BINANCE_DEPTH_SNAPSHOT_URL}?symbol={symbol}&limit=1000"
    with urllib.request.urlopen(url, timeout=10) as response:
        payload = json.loads(response.read().decode("utf-8"))
    return int(payload["lastUpdateId"])


class RawBinanceCollector:
    """Capture exact transport text, then validate per-symbol depth
    continuity separately (`BinanceDepthSequenceGate`, REST-snapshot-bridged)."""

    def __init__(
        self,
        symbols: tuple[str, ...],
        data_dir: Path,
        *,
        market_type: str = "linear",
        flush_interval_secs: float = 5.0,
        max_batch_events: int = 10_000,
        queue_capacity: int = 100_000,
        ping_interval_secs: float = 20.0,
        ping_timeout_secs: float = 10.0,
        health_interval_secs: float = 5.0,
        minimum_runtime_free_gib: float = 5.0,
        reconnect_min_secs: float = 1.0,
        reconnect_max_secs: float = 30.0,
        collector_id: str = "all",
        ws_app_factory: Callable[..., Any] | None = None,
        depth_snapshot_fetcher: Callable[[str], int] | None = None,
        wall_clock_ns: Callable[[], int] = time.time_ns,
        monotonic: Callable[[], float] = time.monotonic,
        disk_usage: Callable[[Path], Any] = shutil.disk_usage,
    ) -> None:
        if not symbols:
            raise ValueError("at least one symbol is required")
        if len(set(symbols)) != len(symbols):
            raise ValueError("symbols must be unique")
        if (
            flush_interval_secs <= 0
            or max_batch_events <= 0
            or queue_capacity <= 0
            or minimum_runtime_free_gib <= 0
        ):
            raise ValueError("flush interval, batch size, and queue capacity must be positive")
        if ping_interval_secs <= 0 or ping_timeout_secs <= 0:
            raise ValueError("ping interval and timeout must be positive")
        if ping_timeout_secs >= ping_interval_secs:
            raise ValueError("ping timeout must be smaller than the ping interval")
        if not re.fullmatch(r"[a-z0-9_-]+", collector_id):
            raise ValueError("collector_id must contain only lowercase letters, digits, _ or -")

        self.symbols = symbols
        self.data_dir = Path(data_dir)
        self.market_type = market_type
        self.flush_interval_secs = flush_interval_secs
        self.max_batch_events = max_batch_events
        self.ping_interval_secs = ping_interval_secs
        self.ping_timeout_secs = ping_timeout_secs
        self.health_interval_secs = health_interval_secs
        self.minimum_runtime_free_bytes = int(minimum_runtime_free_gib * 1024**3)
        self.reconnect_min_secs = reconnect_min_secs
        self.reconnect_max_secs = reconnect_max_secs
        self.collector_id = collector_id
        self._ws_app_factory = ws_app_factory or self._default_ws_app_factory
        self._depth_snapshot_fetcher = depth_snapshot_fetcher or default_depth_snapshot_fetcher
        self._wall_clock_ns = wall_clock_ns
        self._monotonic = monotonic
        self._disk_usage = disk_usage

        self._queue: queue.Queue[RawMarketEvent] = queue.Queue(maxsize=queue_capacity)
        self._raw_writer = AtomicRawWriter(self.data_dir)
        self.health = CollectorHealth(
            exchange="binance",
            market_type=market_type,
            symbols=symbols,
            collector_id=collector_id,
            storage_runtime_minimum_free_bytes=self.minimum_runtime_free_bytes,
            wall_clock_ns=wall_clock_ns,
            sequence_continuity_verified=True,
        )
        self._health_publisher = AtomicHealthPublisher(
            self.data_dir / "health" / f"binance-{market_type}-{collector_id}.json"
        )
        self._shutdown = threading.Event()
        self._background_stop = threading.Event()
        self._connection_stop = threading.Event()
        self._writer_thread: threading.Thread | None = None
        self._health_thread: threading.Thread | None = None
        self._active_ws: Any = None
        self._connection_id = ""
        self._connection_event_count = 0
        self._receive_sequence = 0
        self._books: dict[str, BinanceDepthSequenceGate] = {}
        self._sequence_uncertain = False
        self._writer_failure: BaseException | None = None
        self._terminal_failure: BaseException | None = None

    @staticmethod
    def _default_ws_app_factory(url: str, **callbacks: Any) -> Any:
        import websocket

        return websocket.WebSocketApp(url, **callbacks)

    @property
    def subscribe_streams(self) -> tuple[str, ...]:
        return tuple(
            f"{symbol.lower()}@{suffix}"
            for symbol in self.symbols
            for suffix in BINANCE_STREAM_SUFFIXES
        )

    def run_forever(self) -> None:
        original_sigterm = signal.getsignal(signal.SIGTERM)
        original_sigint = signal.getsignal(signal.SIGINT)
        signal.signal(signal.SIGTERM, self._handle_stop_signal)
        signal.signal(signal.SIGINT, self._handle_stop_signal)
        self._start_background_workers()
        reconnect_delay = self.reconnect_min_secs
        first_connection = True
        try:
            self._enforce_storage_reserve()
            while not self._shutdown.is_set():
                if not first_connection:
                    self.health.record_reconnect()
                first_connection = False
                self._prepare_connection()
                ws = self._ws_app_factory(
                    BINANCE_FUTURES_WS,
                    on_open=self._on_open,
                    on_message=self._on_message,
                    on_error=self._on_error,
                    on_close=self._on_close,
                )
                self._active_ws = ws
                ws.run_forever(
                    ping_interval=self.ping_interval_secs, ping_timeout=self.ping_timeout_secs
                )
                self._connection_stop.set()
                if self._shutdown.is_set():
                    break
                if self._connection_event_count > 0:
                    reconnect_delay = self.reconnect_min_secs
                log.warning(
                    "Binance raw collector reconnecting",
                    delay_secs=reconnect_delay,
                    connection_id=self._connection_id,
                )
                self._shutdown.wait(reconnect_delay)
                reconnect_delay = min(reconnect_delay * 2, self.reconnect_max_secs)
        finally:
            signal.signal(signal.SIGTERM, original_sigterm)
            signal.signal(signal.SIGINT, original_sigint)
            self.stop()
        if self._writer_failure is not None:
            raise RuntimeError("raw writer failed") from self._writer_failure
        if self._terminal_failure is not None:
            raise RuntimeError("raw collector stopped by a fail-closed guard") from (
                self._terminal_failure
            )

    def stop(self) -> None:
        self.health.mark_stopping()
        self._shutdown.set()
        self._connection_stop.set()
        active_ws = self._active_ws
        if active_ws is not None:
            try:
                active_ws.close()
            except Exception as exc:  # pragma: no cover - defensive SDK boundary
                self.health.record_error(f"WebSocket close failed: {exc}")
        self._background_stop.set()
        for thread in (self._writer_thread, self._health_thread):
            if thread is not None and thread is not threading.current_thread():
                thread.join(timeout=max(30.0, self.flush_interval_secs * 2))
        failed = self._writer_failure is not None or self._terminal_failure is not None
        self.health.mark_stopped(failed=failed)
        self._publish_health()

    def handle_raw_message(self, payload: str | bytes) -> None:
        """Public test seam used by the real WebSocket callback."""
        if isinstance(payload, bytes):
            try:
                payload_text = payload.decode("utf-8", errors="strict")
            except UnicodeDecodeError as exc:
                self._fail_closed(f"non-UTF-8 WebSocket message: {exc}")
                return
        else:
            payload_text = payload

        receive_ts_ns = self._wall_clock_ns()
        self._receive_sequence += 1
        try:
            event = parse_binance_message(
                payload_text,
                receive_ts_ns=receive_ts_ns,
                connection_id=self._connection_id,
                market_type=self.market_type,
                receive_sequence=self._receive_sequence,
            )
        except RawEventError as exc:
            self._fail_closed(f"raw message could not be enveloped: {exc}")
            return

        try:
            self._queue.put_nowait(event)
        except queue.Full:
            self._fail_closed("raw event queue is full; collector stopped before silent loss")
            return
        self._connection_event_count += 1
        self.health.record_event(
            channel=event.channel,
            symbol=event.symbol,
            receive_ts_ns=event.receive_ts_ns,
        )

        if self._sequence_uncertain or event.channel != "orderbook":
            return
        try:
            self._books[event.symbol].apply(event)
        except (BinanceReplayError, KeyError) as exc:
            self._sequence_uncertain = True
            reason = f"sequence uncertainty requires reconnect: {exc}"
            self.health.record_sequence_uncertainty(reason)
            self._publish_health()
            active_ws = self._active_ws
            if active_ws is not None:
                active_ws.close()

    def _prepare_connection(self) -> None:
        self._connection_id = uuid.uuid4().hex
        self._connection_event_count = 0
        self._connection_stop = threading.Event()
        self._books = {symbol: BinanceDepthSequenceGate(symbol) for symbol in self.symbols}
        self._sequence_uncertain = False

    def _bootstrap_depth_gates(self) -> None:
        for symbol in self.symbols:
            try:
                snapshot_update_id = self._depth_snapshot_fetcher(symbol)
            except Exception as exc:  # any fetch failure is fail-closed, not fatal
                self.health.record_error(f"depth snapshot fetch failed for {symbol}: {exc}")
                continue
            self._books[symbol].bootstrap(
                snapshot_update_id=snapshot_update_id, connection_id=self._connection_id
            )

    def _on_open(self, ws: Any) -> None:
        if not self._enforce_storage_reserve():
            return
        self.health.mark_connected(self._connection_id)
        request = {
            "method": "SUBSCRIBE",
            "params": list(self.subscribe_streams),
            "id": 1,
        }
        ws.send(json.dumps(request, separators=(",", ":")))
        self._bootstrap_depth_gates()
        self._publish_health()

    def _on_message(self, ws: Any, payload: str | bytes) -> None:
        self.handle_raw_message(payload)

    def _on_error(self, ws: Any, error: object) -> None:
        self.health.record_error(f"WebSocket error: {error}")

    def _on_close(self, ws: Any, status_code: object, message: object) -> None:
        self._connection_stop.set()
        reason = f"WebSocket closed: code={status_code!r}, message={message!r}"
        self.health.mark_disconnected(reason)
        self._publish_health()

    def _start_background_workers(self) -> None:
        if self._writer_thread is not None:
            return
        self._writer_thread = threading.Thread(
            target=self._writer_loop, name="binance-raw-writer", daemon=False
        )
        self._health_thread = threading.Thread(
            target=self._health_loop, name="binance-health-publisher", daemon=False
        )
        self._writer_thread.start()
        self._health_thread.start()

    def _writer_loop(self) -> None:
        batch: list[RawMarketEvent] = []
        deadline = self._monotonic() + self.flush_interval_secs
        try:
            while not self._background_stop.is_set() or not self._queue.empty() or batch:
                timeout = max(0.0, deadline - self._monotonic())
                try:
                    event = self._queue.get(timeout=min(timeout, 0.5))
                    batch.append(event)
                except queue.Empty:
                    pass

                due = self._monotonic() >= deadline
                if batch and (
                    due
                    or len(batch) >= self.max_batch_events
                    or (self._background_stop.is_set() and self._queue.empty())
                ):
                    manifests = self._raw_writer.write(batch)
                    last_manifest = manifests[-1].manifest_path if manifests else None
                    self.health.record_flush(
                        event_count=len(batch),
                        part_count=len(manifests),
                        queue_depth=self._queue.qsize(),
                        last_manifest_path=last_manifest,
                    )
                    for _ in batch:
                        self._queue.task_done()
                    batch = []
                    deadline = self._monotonic() + self.flush_interval_secs
        except BaseException as exc:
            self._writer_failure = exc
            self.health.record_drop(f"raw writer failed: {exc}")
            self._shutdown.set()
            active_ws = self._active_ws
            if active_ws is not None:
                active_ws.close()
        finally:
            self._publish_health()

    def _health_loop(self) -> None:
        while not self._background_stop.wait(self.health_interval_secs):
            if not self._enforce_storage_reserve():
                return
            self._publish_health()

    def _enforce_storage_reserve(self) -> bool:
        try:
            available = int(self._disk_usage(self.data_dir).free)
        except OSError as exc:
            reason = f"storage capacity probe failed: {exc}"
            self._terminal_failure = self._terminal_failure or RuntimeError(reason)
            self.health.record_fatal(reason)
            self._publish_health()
            self._shutdown.set()
            active_ws = self._active_ws
            if active_ws is not None:
                active_ws.close()
            return False
        if available >= self.minimum_runtime_free_bytes:
            return True
        reason = (
            "storage reserve breached; collector stopped before ENOSPC: "
            f"available_bytes={available}; "
            f"required_bytes={self.minimum_runtime_free_bytes}"
        )
        self._terminal_failure = self._terminal_failure or RuntimeError(reason)
        self.health.record_fatal(reason)
        self._publish_health()
        self._shutdown.set()
        active_ws = self._active_ws
        if active_ws is not None:
            active_ws.close()
        return False

    def _publish_health(self) -> None:
        try:
            self._health_publisher.publish(
                self.health.snapshot(queue_depth=self._queue.qsize())
            )
        except OSError as exc:
            self._writer_failure = self._writer_failure or exc
            self._shutdown.set()

    def _fail_closed(self, reason: str) -> None:
        self.health.record_drop(reason)
        self._publish_health()
        self._shutdown.set()
        active_ws = self._active_ws
        if active_ws is not None:
            active_ws.close()

    def _handle_stop_signal(self, signum: int, frame: object) -> None:
        self._shutdown.set()
        active_ws = self._active_ws
        if active_ws is not None:
            active_ws.close()
