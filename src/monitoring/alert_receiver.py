"""Durable Alertmanager webhook receiver with optional HTTPS forwarding.

The receiver is deliberately independent of any notification vendor. Every
valid Alertmanager delivery is fsynced to a daily JSONL audit journal before an
optional external webhook is attempted. Alertmanager receives a non-2xx
response when forwarding fails so its normal retry semantics remain active.
"""

from __future__ import annotations

import hashlib
import json
import os
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

DEFAULT_MAX_BODY_BYTES = 1_048_576
DEFAULT_FORWARD_TIMEOUT_SECS = 10.0


class InvalidAlertPayload(ValueError):
    """Raised when a request is not a bounded Alertmanager webhook payload."""


class ForwardingError(RuntimeError):
    """Raised after a durable receipt when the external webhook failed."""


@dataclass(frozen=True)
class DeliveryResult:
    event_id: str
    alert_count: int
    journal_path: Path
    forwarded: bool


class ReceiverMetrics:
    """Small thread-safe metric set exposed directly to Prometheus."""

    def __init__(self, *, wall_clock: Callable[[], float] = time.time) -> None:
        self._wall_clock = wall_clock
        self._lock = threading.Lock()
        self._started_at = wall_clock()
        self._received_webhooks = 0
        self._received_alerts = 0
        self._stored_records = 0
        self._forward_failures = 0
        self._last_received_at = 0.0

    def record_received(self, alert_count: int) -> None:
        with self._lock:
            self._received_webhooks += 1
            self._received_alerts += alert_count
            self._last_received_at = self._wall_clock()

    def record_stored(self) -> None:
        with self._lock:
            self._stored_records += 1

    def record_forward_failure(self) -> None:
        with self._lock:
            self._forward_failures += 1

    def render_prometheus(self) -> str:
        with self._lock:
            values = {
                "greenfield_alert_receiver_up": 1,
                "greenfield_alert_receiver_start_timestamp_seconds": self._started_at,
                "greenfield_alert_receiver_received_webhooks_total": (
                    self._received_webhooks
                ),
                "greenfield_alert_receiver_received_alerts_total": self._received_alerts,
                "greenfield_alert_receiver_stored_records_total": self._stored_records,
                "greenfield_alert_receiver_forward_failures_total": self._forward_failures,
                "greenfield_alert_receiver_last_received_timestamp_seconds": (
                    self._last_received_at
                ),
            }
        lines: list[str] = []
        for name, value in values.items():
            metric_type = "counter" if name.endswith("_total") else "gauge"
            lines.extend((f"# TYPE {name} {metric_type}", f"{name} {value}"))
        return "\n".join(lines) + "\n"


class AlertJournal:
    """Append-only, daily JSONL journal with a durability boundary per record."""

    def __init__(self, root: Path) -> None:
        self.root = Path(root)
        self._lock = threading.Lock()

    def append(self, record: Mapping[str, Any], *, received_at_ns: int) -> Path:
        date = datetime.fromtimestamp(received_at_ns / 1_000_000_000, tz=UTC).date()
        path = self.root / f"{date.isoformat()}.jsonl"
        line = json.dumps(record, sort_keys=True, separators=(",", ":")) + "\n"
        with self._lock:
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open("a", encoding="utf-8", newline="\n") as handle:
                handle.write(line)
                handle.flush()
                os.fsync(handle.fileno())
        return path


class HttpsWebhookForwarder:
    """Forward JSON to one explicit HTTPS endpoint without logging secrets."""

    def __init__(
        self,
        url: str,
        *,
        bearer_token: str | None = None,
        timeout_secs: float = DEFAULT_FORWARD_TIMEOUT_SECS,
    ) -> None:
        parsed = urllib.parse.urlsplit(url)
        if parsed.scheme != "https" or not parsed.netloc:
            raise ValueError("ALERT_FORWARD_URL must be an absolute HTTPS URL")
        if timeout_secs <= 0:
            raise ValueError("forward timeout must be positive")
        self._url = url
        self._bearer_token = bearer_token
        self._timeout_secs = timeout_secs

    def __call__(self, payload: Mapping[str, Any], event_id: str) -> None:
        body = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
        headers = {
            "Content-Type": "application/json",
            "User-Agent": "greenfield-alert-receiver/1",
            "X-Greenfield-Event-ID": event_id,
        }
        if self._bearer_token:
            headers["Authorization"] = f"Bearer {self._bearer_token}"
        request = urllib.request.Request(
            self._url,
            data=body,
            headers=headers,
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=self._timeout_secs) as response:
                status = response.status
        except urllib.error.HTTPError as exc:
            raise ForwardingError(f"external webhook returned HTTP {exc.code}") from exc
        except urllib.error.URLError as exc:
            reason = type(exc.reason).__name__
            raise ForwardingError(f"external webhook transport failed ({reason})") from exc
        except TimeoutError as exc:
            raise ForwardingError("external webhook timed out") from exc
        if status < 200 or status >= 300:
            raise ForwardingError(f"external webhook returned HTTP {status}")


class AlertDeliveryProcessor:
    """Validate, journal, and optionally forward one Alertmanager delivery."""

    def __init__(
        self,
        journal: AlertJournal,
        *,
        forwarder: Callable[[Mapping[str, Any], str], None] | None = None,
        metrics: ReceiverMetrics | None = None,
        wall_clock_ns: Callable[[], int] = time.time_ns,
    ) -> None:
        self._journal = journal
        self._forwarder = forwarder
        self.metrics = metrics or ReceiverMetrics()
        self._wall_clock_ns = wall_clock_ns

    def process(self, payload: Any) -> DeliveryResult:
        validated = validate_alertmanager_payload(payload)
        received_at_ns = self._wall_clock_ns()
        event_id = _event_id(validated)
        alert_count = len(validated["alerts"])
        self.metrics.record_received(alert_count)
        receipt = {
            "schema_version": 1,
            "record_type": "alertmanager_receipt",
            "event_id": event_id,
            "received_at_ns": received_at_ns,
            "payload": validated,
        }
        journal_path = self._journal.append(receipt, received_at_ns=received_at_ns)
        self.metrics.record_stored()

        if self._forwarder is None:
            return DeliveryResult(event_id, alert_count, journal_path, False)
        try:
            self._forwarder(validated, event_id)
        except ForwardingError as exc:
            self.metrics.record_forward_failure()
            self._journal.append(
                {
                    "schema_version": 1,
                    "record_type": "forward_failure",
                    "event_id": event_id,
                    "received_at_ns": self._wall_clock_ns(),
                    "error": str(exc),
                },
                received_at_ns=received_at_ns,
            )
            self.metrics.record_stored()
            raise
        self._journal.append(
            {
                "schema_version": 1,
                "record_type": "forward_success",
                "event_id": event_id,
                "received_at_ns": self._wall_clock_ns(),
            },
            received_at_ns=received_at_ns,
        )
        self.metrics.record_stored()
        return DeliveryResult(event_id, alert_count, journal_path, True)


def validate_alertmanager_payload(payload: Any) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise InvalidAlertPayload("payload must be a JSON object")
    alerts = payload.get("alerts")
    if not isinstance(alerts, list):
        raise InvalidAlertPayload("payload.alerts must be a JSON array")
    if len(alerts) > 1_000:
        raise InvalidAlertPayload("payload contains more than 1000 alerts")
    if payload.get("status") not in {"firing", "resolved"}:
        raise InvalidAlertPayload("payload.status must be firing or resolved")
    for index, alert in enumerate(alerts):
        if not isinstance(alert, dict):
            raise InvalidAlertPayload(f"payload.alerts[{index}] must be an object")
        if alert.get("status") not in {"firing", "resolved"}:
            raise InvalidAlertPayload(
                f"payload.alerts[{index}].status must be firing or resolved"
            )
        if not isinstance(alert.get("labels"), dict):
            raise InvalidAlertPayload(f"payload.alerts[{index}].labels must be an object")
    return payload


def _event_id(payload: Mapping[str, Any]) -> str:
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(canonical).hexdigest()


def create_alert_server(
    address: tuple[str, int],
    processor: AlertDeliveryProcessor,
    *,
    max_body_bytes: int = DEFAULT_MAX_BODY_BYTES,
) -> ThreadingHTTPServer:
    if max_body_bytes <= 0:
        raise ValueError("max_body_bytes must be positive")

    class Handler(BaseHTTPRequestHandler):
        server_version = "GreenfieldAlertReceiver/1"

        def do_GET(self) -> None:  # noqa: N802 - stdlib handler API
            if self.path == "/health":
                self._json_response(HTTPStatus.OK, {"status": "ok"})
                return
            if self.path == "/metrics":
                body = processor.metrics.render_prometheus().encode()
                self.send_response(HTTPStatus.OK)
                self.send_header("Content-Type", "text/plain; version=0.0.4")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
                return
            self._json_response(HTTPStatus.NOT_FOUND, {"error": "not found"})

        def do_POST(self) -> None:  # noqa: N802 - stdlib handler API
            if self.path != "/alerts":
                self._json_response(HTTPStatus.NOT_FOUND, {"error": "not found"})
                return
            content_length = self.headers.get("Content-Length")
            if content_length is None:
                self._json_response(HTTPStatus.LENGTH_REQUIRED, {"error": "length required"})
                return
            try:
                length = int(content_length)
            except ValueError:
                self._json_response(HTTPStatus.BAD_REQUEST, {"error": "invalid length"})
                return
            if length < 0 or length > max_body_bytes:
                self._json_response(
                    HTTPStatus.REQUEST_ENTITY_TOO_LARGE,
                    {"error": "request body too large"},
                )
                return
            try:
                payload = json.loads(self.rfile.read(length))
                result = processor.process(payload)
            except (json.JSONDecodeError, UnicodeDecodeError, InvalidAlertPayload) as exc:
                self._json_response(HTTPStatus.BAD_REQUEST, {"error": str(exc)})
                return
            except ForwardingError as exc:
                self._json_response(HTTPStatus.BAD_GATEWAY, {"error": str(exc)})
                return
            except OSError:
                self._json_response(
                    HTTPStatus.INTERNAL_SERVER_ERROR,
                    {"error": "durable journal write failed"},
                )
                return
            status = HTTPStatus.OK if result.forwarded else HTTPStatus.ACCEPTED
            self._json_response(
                status,
                {
                    "event_id": result.event_id,
                    "alert_count": result.alert_count,
                    "stored": True,
                    "forwarded": result.forwarded,
                },
            )

        def log_message(self, format: str, *args: Any) -> None:
            # Container access logs add little value and can expose a configured path.
            return

        def _json_response(self, status: HTTPStatus, payload: Mapping[str, Any]) -> None:
            body = json.dumps(payload, sort_keys=True).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("X-Content-Type-Options", "nosniff")
            self.end_headers()
            self.wfile.write(body)

    server = ThreadingHTTPServer(address, Handler)
    server.daemon_threads = True
    return server


def build_processor_from_environment(
    *,
    journal_root: Path,
    forward_timeout_secs: float = DEFAULT_FORWARD_TIMEOUT_SECS,
) -> AlertDeliveryProcessor:
    forward_url = os.environ.get("ALERT_FORWARD_URL", "").strip()
    forwarder = None
    if forward_url:
        forwarder = HttpsWebhookForwarder(
            forward_url,
            bearer_token=os.environ.get("ALERT_FORWARD_BEARER_TOKEN") or None,
            timeout_secs=forward_timeout_secs,
        )
    return AlertDeliveryProcessor(AlertJournal(journal_root), forwarder=forwarder)
