"""Lossless, reconnecting OKX public WebSocket collector (Cycle 5).

Structurally mirrors `src.data.bybit_raw_collector.RawBybitCollector` -
same queue/writer/health/storage-reserve/signal-handling shape, proven in
Phase 1 - but is a fully independent module with its own connection,
symbols, and health files so a failure on one exchange's collector can
never affect another's. It is intended to run as its own isolated
service, in the same disabled-by-default profile pattern already used for
`shadow-service` in docker-compose.yml; that deployment wiring (script
entrypoint, compose service, symbol config) is follow-up work and is not
part of this cycle - see docs/CLAUDE_CODE_CONTINUATION.md.

OKX-specific differences from Bybit: subscribe args are per-channel
objects (`{"channel": ..., "instId": ...}`), sequence gating is
`OkxSequenceGate`'s connection-scoped `seqId`/`prevSeqId` (self-bootstraps
from the stream's own first snapshot message, unlike Binance's REST-bridge
requirement), and keepalive is a literal (non-JSON) "ping"/"pong" text
frame rather than a JSON op - handled explicitly before envelope parsing
since "pong" is not valid JSON.

`instId` values are OKX-native (e.g. "BTC-USDT-SWAP") - callers pass them
directly rather than a Bybit-style bare symbol, since OKX's own topic and
symbol identity already use this form (see src/data/okx_adapter.py).
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
from src.data.okx_adapter import OkxReplayError, OkxSequenceGate, parse_okx_message
from src.data.raw_event import RawEventError, RawMarketEvent
from src.data.raw_store import AtomicRawWriter

log = structlog.get_logger()

OKX_PUBLIC_WS = "wss://ws.okx.com:8443/ws/v5/public"
OKX_CHANNELS = ("books", "trades", "tickers")


class RawOkxCollector:
    """Capture exact transport text, then validate book sequence state separately."""

    def __init__(
        self,
        inst_ids: tuple[str, ...],
        data_dir: Path,
        *,
        market_type: str = "swap",
        flush_interval_secs: float = 5.0,
        max_batch_events: int = 10_000,
        queue_capacity: int = 100_000,
        ping_interval_secs: float = 20.0,
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
        if not inst_ids:
            raise ValueError("at least one instId is required")
        if len(set(inst_ids)) != len(inst_ids):
            raise ValueError("instIds must be unique")
        if (
            flush_interval_secs <= 0
            or max_batch_events <= 0
            or queue_capacity <= 0
            or minimum_runtime_free_gib <= 0
        ):
            raise ValueError("flush interval, batch size, and queue capacity must be positive")
        if not re.fullmatch(r"[a-z0-9_-]+", collector_id):
            raise ValueError("collector_id must contain only lowercase letters, digits, _ or -")

        self.inst_ids = inst_ids
        self.data_dir = Path(data_dir)
        self.market_type = market_type
        self.flush_interval_secs = flush_interval_secs
        self.max_batch_events = max_batch_events
        self.ping_interval_secs = ping_interval_secs
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
            exchange="okx",
            market_type=market_type,
            symbols=inst_ids,
            collector_id=collector_id,
            storage_runtime_minimum_free_bytes=self.minimum_runtime_free_bytes,
            wall_clock_ns=wall_clock_ns,
        )
        self._health_publisher = AtomicHealthPublisher(
            self.data_dir / "health" / f"okx-{market_type}-{collector_id}.json"
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
        self._books: dict[str, OkxSequenceGate] = {}
        self._sequence_uncertain = False
        self._writer_failure: BaseException | None = None
        self._terminal_failure: BaseException | None = None

    @staticmethod
    def _default_ws_app_factory(url: str, **callbacks: Any) -> Any:
        import websocket

        return websocket.WebSocketApp(url, **callbacks)

    @property
    def subscribe_args(self) -> tuple[dict[str, str], ...]:
        return tuple(
            {"channel": channel, "instId": inst_id}
            for inst_id in self.inst_ids
            for channel in OKX_CHANNELS
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
                    OKX_PUBLIC_WS,
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
                    "OKX raw collector reconnecting",
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
        self.request_stop()
        self._background_stop.set()
        for thread in (self._writer_thread, self._health_thread):
            if thread is not None and thread is not threading.current_thread():
                thread.join(timeout=max(30.0, self.flush_interval_secs * 2))
        failed = self._writer_failure is not None or self._terminal_failure is not None
        self.health.mark_stopped(failed=failed)
        self._publish_health()

    def request_stop(self) -> None:
        """Wake the foreground loop; final flushing remains in ``stop``."""

        self._shutdown.set()
        self._connection_stop.set()
        active_ws = self._active_ws
        if active_ws is not None:
            try:
                active_ws.close()
            except Exception as exc:  # pragma: no cover - defensive SDK boundary
                self.health.record_error(f"WebSocket close failed: {exc}")

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

        if payload_text.strip() == "pong":
            return  # transport-level keepalive reply, not a JSON envelope

        receive_ts_ns = self._wall_clock_ns()
        self._receive_sequence += 1
        try:
            event = parse_okx_message(
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
        except (OkxReplayError, KeyError) as exc:
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
        self._books = {inst_id: OkxSequenceGate(inst_id) for inst_id in self.inst_ids}
        self._sequence_uncertain = False

    def _on_open(self, ws: Any) -> None:
        if not self._enforce_storage_reserve():
            return
        self.health.mark_connected(self._connection_id)
        request = {"op": "subscribe", "args": list(self.subscribe_args)}
        ws.send(json.dumps(request, separators=(",", ":")))
        threading.Thread(
            target=self._ping_loop,
            args=(ws, self._connection_stop),
            name=f"okx-ping-{self._connection_id[:8]}",
            daemon=True,
        ).start()
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

    def _ping_loop(self, ws: Any, connection_stop: threading.Event) -> None:
        while not self._shutdown.is_set() and not connection_stop.wait(self.ping_interval_secs):
            try:
                ws.send("ping")
            except Exception as exc:  # pragma: no cover - network race
                self.health.record_error(f"WebSocket ping failed: {exc}")
                ws.close()
                return

    def _start_background_workers(self) -> None:
        if self._writer_thread is not None:
            return
        self._writer_thread = threading.Thread(
            target=self._writer_loop, name="okx-raw-writer", daemon=False
        )
        self._health_thread = threading.Thread(
            target=self._health_loop, name="okx-health-publisher", daemon=False
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
            self._health_publisher.publish(self.health.snapshot(queue_depth=self._queue.qsize()))
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
        self.request_stop()
