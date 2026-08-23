"""Lossless, reconnecting Coinbase Advanced Trade public WebSocket collector
(Cycle 5).

Structurally mirrors `src.data.bybit_raw_collector.RawBybitCollector` and
`src.data.okx_raw_collector.RawOkxCollector` - same queue/writer/health/
storage-reserve/signal-handling shape - but is a fully independent module
with its own connection, symbols, and health files so a failure here can
never affect another exchange's collector.

Coinbase-specific differences: one subscribe message per channel (`level2`,
`market_trades`, `ticker`), and keepalive uses the standard WebSocket
protocol ping/pong frames via `ws.run_forever(ping_interval=...)` rather
than an application-level JSON ping message (verified against the live
public endpoint: continuous `level2`/`market_trades` traffic with no
app-level ping required).

NOT wired here: `src.data.coinbase_adapter.CoinbaseLevel2SequenceGate`'s
live continuity enforcement. That gate assumes `sequence_num` is a
strictly-consecutive stream for one product's `l2_data` messages alone.
Live protocol probing against the real endpoint (2026-08-23) proved this
false: `sequence_num` is connection-global across every message Coinbase
sends on that connection, including its own automatic `subscriptions`
acknowledgement - a single-product, level2-only subscription still showed
sequence 0, 1, 2 consumed by a `channel: "subscriptions"` message, 3,
4, ... Applying that per-product gate live against a multi-product/
multi-channel connection produced spurious `CoinbaseSequenceGap` errors
and forced reconnects with zero actual data loss (`dropped_event_count`
stayed 0 throughout).

SEQUENCE CONTINUITY (Cycle 8): wired instead is
`src.data.coinbase_adapter.CoinbaseConnectionSequenceGate` - tracks one
running `sequence_num` counter shared by *every* message on the
connection, matching the protocol behavior actually observed above.
Bootstraps from whatever the first observed `sequence_num` is (never
assumes 0); a `connection_id` change (reconnect) resets and re-bootstraps
rather than being treated as a rollback; any other discontinuity - a
forward gap, an exact duplicate, or the counter going backward - raises a
distinct, named exception (`CoinbaseSequenceGap`/`-Duplicate`/`-Rollback`)
and is handled exactly like OKX's/Bybit's replay gates: mark
sequence-uncertain, record it in health, force a reconnect. Every message
still reaches the queue *before* this gate runs (raw capture stays
unaffected by a gate failure), and messages without `sequence_num` simply
aren't checked - a missing field is not evidence of a gap by itself. See
`CoinbaseConnectionSequenceGate`'s own docstring for the full design.
`self.health` is now constructed with `sequence_continuity_verified=True`.

Deployment wiring (`scripts/collect_raw_coinbase.py`, `docker-compose.yml`'s
`raw-coinbase-*` services, `raw_collector_config.py` support) was out of
scope for this cycle (the sequence-gate fix only) but was added in Cycle
9 - see docs/CLAUDE_CODE_CONTINUATION.md's Cycle 9 section. Like every
other non-Bybit raw collector in this repo, it is repo-only: disabled by
default behind a Compose profile and gated by
`src.data.raw_collector_start_gate.validate_raw_collector_start`, which
requires an explicit soak marker authorizing its `collector_id` before it
can open a connection - it is not deployed to the VPS.

`product_ids` are Coinbase-native (e.g. "BTC-USD").
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

from src.data.coinbase_adapter import (
    CoinbaseConnectionSequenceGate,
    CoinbaseReplayError,
    parse_coinbase_message,
)
from src.data.collector_health import AtomicHealthPublisher, CollectorHealth
from src.data.raw_event import RawEventError, RawMarketEvent
from src.data.raw_store import AtomicRawWriter

log = structlog.get_logger()

COINBASE_PUBLIC_WS = "wss://advanced-trade-ws.coinbase.com"
COINBASE_CHANNELS = ("level2", "market_trades", "ticker")


class RawCoinbaseCollector:
    """Capture exact transport text, then verify connection-global sequence
    continuity separately (`CoinbaseConnectionSequenceGate` - see module
    docstring). `self.health` is constructed with
    `sequence_continuity_verified=True`.
    """

    def __init__(
        self,
        product_ids: tuple[str, ...],
        data_dir: Path,
        *,
        market_type: str = "spot",
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
        wall_clock_ns: Callable[[], int] = time.time_ns,
        monotonic: Callable[[], float] = time.monotonic,
        disk_usage: Callable[[Path], Any] = shutil.disk_usage,
    ) -> None:
        if not product_ids:
            raise ValueError("at least one product_id is required")
        if len(set(product_ids)) != len(product_ids):
            raise ValueError("product_ids must be unique")
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

        self.product_ids = product_ids
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
        self._wall_clock_ns = wall_clock_ns
        self._monotonic = monotonic
        self._disk_usage = disk_usage

        self._queue: queue.Queue[RawMarketEvent] = queue.Queue(maxsize=queue_capacity)
        self._raw_writer = AtomicRawWriter(self.data_dir)
        self.health = CollectorHealth(
            exchange="coinbase",
            market_type=market_type,
            symbols=product_ids,
            collector_id=collector_id,
            storage_runtime_minimum_free_bytes=self.minimum_runtime_free_bytes,
            wall_clock_ns=wall_clock_ns,
            # See this class's and the module's docstrings: a working
            # connection-global sequence gate is wired (Cycle 8).
            sequence_continuity_verified=True,
        )
        self._health_publisher = AtomicHealthPublisher(
            self.data_dir / "health" / f"coinbase-{market_type}-{collector_id}.json"
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
        self._sequence_gate = CoinbaseConnectionSequenceGate()
        self._sequence_uncertain = False
        self._writer_failure: BaseException | None = None
        self._terminal_failure: BaseException | None = None

    @staticmethod
    def _default_ws_app_factory(url: str, **callbacks: Any) -> Any:
        import websocket

        return websocket.WebSocketApp(url, **callbacks)

    @property
    def subscribe_messages(self) -> tuple[dict[str, Any], ...]:
        return tuple(
            {"type": "subscribe", "product_ids": list(self.product_ids), "channel": channel}
            for channel in COINBASE_CHANNELS
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
                    COINBASE_PUBLIC_WS,
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
                    "Coinbase raw collector reconnecting",
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
            event = parse_coinbase_message(
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

        if self._sequence_uncertain:
            return
        try:
            self._sequence_gate.observe(event)
        except CoinbaseReplayError as exc:
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
        self._sequence_gate = CoinbaseConnectionSequenceGate()
        self._sequence_uncertain = False

    def _on_open(self, ws: Any) -> None:
        if not self._enforce_storage_reserve():
            return
        self.health.mark_connected(self._connection_id)
        for message in self.subscribe_messages:
            ws.send(json.dumps(message, separators=(",", ":")))
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
            target=self._writer_loop, name="coinbase-raw-writer", daemon=False
        )
        self._health_thread = threading.Thread(
            target=self._health_loop, name="coinbase-health-publisher", daemon=False
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
