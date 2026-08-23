"""Lossless, reconnecting Deribit public JSON-RPC WebSocket collector
(Cycle 11).

Structurally mirrors `src.data.okx_raw_collector.RawOkxCollector` - same
queue/writer/health/storage-reserve/signal-handling shape - built on top
of the pre-existing `src.data.deribit_adapter` contract
(`parse_deribit_message`, `DeribitBookSequenceGate`; commit `4595827`,
predating this collector) rather than reinventing it. `DeribitBookSequenceGate`
self-bootstraps from the first `"snapshot"` message per instrument on a
connection and enforces strict `change_id`/`prev_change_id` continuity for
subsequent `"change"` messages - the same shape as OKX's `seqId`/
`prevSeqId` gate, not Binance's REST-snapshot-bridge (see
`src.data.binance_raw_collector`).

Live-verified in this session (2026-08-23) against `wss://www.deribit.com/
ws/api/v2`: `public/subscribe` result envelope, `book.*` snapshot/change
messages (including `change_id`/`prev_change_id` matching the adapter's
assumptions exactly), `ticker.*` messages, and the `public/set_heartbeat`
-> periodic `{"method":"heartbeat","params":{"type":"test_request"}}` ->
`public/test` reply cycle (Deribit's documented liveness mechanism - the
connection stayed open through it). `trades.*` was subscribed but produced
no message in the ~20s test window (BTC-PERPETUAL simply didn't trade in
that window) - not a schema concern, since `src.data.deribit_adapter`'s
trades handling was already exercised by its own pre-existing test suite.

Instrument universe (this cycle): perpetuals only - `BTC-PERPETUAL` and
`ETH-PERPETUAL`. Verified live via `GET /public/get_instruments` that
Deribit lists **zero** SOL futures/perpetual/option instruments (SOL
exists only as a currency/collateral asset there), so SOL is excluded
rather than guessed - this is a real product-availability fact, not
something deferred. Dated BTC/ETH futures (a rolling, expiry-driven list
of ~10+ instruments per currency) and options (an even larger, more
frequently changing chain) are NOT included in this cycle: unlike the
fixed-name perpetual/spot universes every other collector in this
repository uses, both need a dynamic instrument-discovery mechanism
(polling `public/get_instruments`, resubscribing as contracts list/expire)
that does not exist yet. This is tracked as explicit follow-up work, not
represented as done - IV/skew/term-structure data is entirely options-
derived, so none of it is captured by this cycle either. `ticker.*`
already carries every field Deribit sends (mark/index price, funding,
open interest, stats) generically through to Silver via
`src.data.deribit_normalized_event._ticker_records`, so once an options
instrument list exists, IV/greeks flow through with no normalizer changes.

Deribit-specific differences from OKX: JSON-RPC request/response framing
(`public/subscribe`, `public/set_heartbeat`) rather than a bare
`{"op": "subscribe", ...}` message; keepalive is Deribit's own documented
heartbeat/test_request exchange (a `test_request` heartbeat left
unanswered eventually gets the connection dropped server-side) rather
than a raw WebSocket ping frame or transport-level `ping_interval`.

`instruments` are Deribit-native (e.g. "BTC-PERPETUAL").
"""

from __future__ import annotations

import json
import queue
import re
import shutil
import signal
import threading
import time
import uuid
from collections.abc import Callable
from pathlib import Path
from typing import Any

import structlog

from src.data.collector_health import AtomicHealthPublisher, CollectorHealth
from src.data.deribit_adapter import (
    DeribitBookSequenceGate,
    DeribitReplayError,
    parse_deribit_message,
)
from src.data.raw_event import RawEventError, RawMarketEvent
from src.data.raw_store import AtomicRawWriter

log = structlog.get_logger()

DERIBIT_PUBLIC_WS = "wss://www.deribit.com/ws/api/v2"
DERIBIT_CHANNEL_KINDS = ("book", "trades", "ticker")


class RawDeribitCollector:
    """Capture exact transport text, then validate per-instrument book
    continuity separately (`DeribitBookSequenceGate`)."""

    def __init__(
        self,
        instruments: tuple[str, ...],
        data_dir: Path,
        *,
        market_type: str = "future",
        channel_interval: str = "100ms",
        flush_interval_secs: float = 5.0,
        max_batch_events: int = 10_000,
        queue_capacity: int = 100_000,
        heartbeat_interval_secs: int = 30,
        health_interval_secs: float = 5.0,
        minimum_runtime_free_gib: float = 5.0,
        reconnect_min_secs: float = 1.0,
        reconnect_max_secs: float = 30.0,
        collector_id: str = "all",
        ws_app_factory: Callable[..., Any] | None = None,
        wall_clock_ns: Callable[[], int] = time.time_ns,
        monotonic: Callable[[], float] = time.monotonic,
        disk_usage: Callable[[Path], Any] = shutil.disk_usage,
    ) -> None:
        if not instruments:
            raise ValueError("at least one instrument is required")
        if len(set(instruments)) != len(instruments):
            raise ValueError("instruments must be unique")
        if (
            flush_interval_secs <= 0
            or max_batch_events <= 0
            or queue_capacity <= 0
            or minimum_runtime_free_gib <= 0
        ):
            raise ValueError("flush interval, batch size, and queue capacity must be positive")
        if heartbeat_interval_secs < 10:
            raise ValueError("Deribit requires a heartbeat interval of at least 10 seconds")
        if not re.fullmatch(r"[a-z0-9_-]+", collector_id):
            raise ValueError("collector_id must contain only lowercase letters, digits, _ or -")

        self.instruments = instruments
        self.data_dir = Path(data_dir)
        self.market_type = market_type
        self.channel_interval = channel_interval
        self.flush_interval_secs = flush_interval_secs
        self.max_batch_events = max_batch_events
        self.heartbeat_interval_secs = heartbeat_interval_secs
        self.health_interval_secs = health_interval_secs
        self.minimum_runtime_free_bytes = int(minimum_runtime_free_gib * 1024**3)
        self.reconnect_min_secs = reconnect_min_secs
        self.reconnect_max_secs = reconnect_max_secs
        self.collector_id = collector_id
        self._ws_app_factory = ws_app_factory or self._default_ws_app_factory
        self._wall_clock_ns = wall_clock_ns
        self._monotonic = monotonic
        self._disk_usage = disk_usage

        self._queue: queue.Queue[RawMarketEvent] = queue.Queue(maxsize=queue_capacity)
        self._raw_writer = AtomicRawWriter(self.data_dir)
        self.health = CollectorHealth(
            exchange="deribit",
            market_type=market_type,
            symbols=instruments,
            collector_id=collector_id,
            storage_runtime_minimum_free_bytes=self.minimum_runtime_free_bytes,
            wall_clock_ns=wall_clock_ns,
            sequence_continuity_verified=True,
        )
        self._health_publisher = AtomicHealthPublisher(
            self.data_dir / "health" / f"deribit-{market_type}-{collector_id}.json"
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
        self._books: dict[str, DeribitBookSequenceGate] = {}
        self._sequence_uncertain = False
        self._writer_failure: BaseException | None = None
        self._terminal_failure: BaseException | None = None

    @staticmethod
    def _default_ws_app_factory(url: str, **callbacks: Any) -> Any:
        import websocket

        return websocket.WebSocketApp(url, **callbacks)

    @property
    def subscribe_channels(self) -> tuple[str, ...]:
        return tuple(
            f"{kind}.{instrument}.{self.channel_interval}"
            for instrument in self.instruments
            for kind in DERIBIT_CHANNEL_KINDS
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
                    DERIBIT_PUBLIC_WS,
                    on_open=self._on_open,
                    on_message=self._on_message,
                    on_error=self._on_error,
                    on_close=self._on_close,
                )
                self._active_ws = ws
                ws.run_forever()
                self._connection_stop.set()
                if self._shutdown.is_set():
                    break
                if self._connection_event_count > 0:
                    reconnect_delay = self.reconnect_min_secs
                log.warning(
                    "Deribit raw collector reconnecting",
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
            event = parse_deribit_message(
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

        if event.topic == "heartbeat":
            self._maybe_reply_to_heartbeat(event)

        if self._sequence_uncertain or event.channel != "orderbook":
            return
        try:
            self._books[event.symbol].apply(event)
        except (DeribitReplayError, KeyError) as exc:
            self._sequence_uncertain = True
            reason = f"sequence uncertainty requires reconnect: {exc}"
            self.health.record_sequence_uncertainty(reason)
            self._publish_health()
            active_ws = self._active_ws
            if active_ws is not None:
                active_ws.close()

    def _maybe_reply_to_heartbeat(self, event: RawMarketEvent) -> None:
        try:
            params = event.payload().get("params", {})
        except RawEventError:
            return
        if not isinstance(params, dict) or params.get("type") != "test_request":
            return
        active_ws = self._active_ws
        if active_ws is None:
            return
        try:
            active_ws.send(
                json.dumps(
                    {"jsonrpc": "2.0", "method": "public/test", "params": {}},
                    separators=(",", ":"),
                )
            )
        except Exception as exc:  # pragma: no cover - network race
            self.health.record_error(f"heartbeat test_request reply failed: {exc}")

    def _prepare_connection(self) -> None:
        self._connection_id = uuid.uuid4().hex
        self._connection_event_count = 0
        self._connection_stop = threading.Event()
        self._books = {
            instrument: DeribitBookSequenceGate(instrument) for instrument in self.instruments
        }
        self._sequence_uncertain = False

    def _on_open(self, ws: Any) -> None:
        if not self._enforce_storage_reserve():
            return
        self.health.mark_connected(self._connection_id)
        heartbeat_request = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "public/set_heartbeat",
            "params": {"interval": self.heartbeat_interval_secs},
        }
        ws.send(json.dumps(heartbeat_request, separators=(",", ":")))
        subscribe_request = {
            "jsonrpc": "2.0",
            "id": 2,
            "method": "public/subscribe",
            "params": {"channels": list(self.subscribe_channels)},
        }
        ws.send(json.dumps(subscribe_request, separators=(",", ":")))
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
            target=self._writer_loop, name="deribit-raw-writer", daemon=False
        )
        self._health_thread = threading.Thread(
            target=self._health_loop, name="deribit-health-publisher", daemon=False
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
