"""Durability, validation, forwarding, and HTTP behavior for alert delivery."""

from __future__ import annotations

import json
import threading
import urllib.error
import urllib.request
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import pytest

from src.monitoring.alert_receiver import (
    AlertDeliveryProcessor,
    AlertJournal,
    ForwardingError,
    HttpsWebhookForwarder,
    InvalidAlertPayload,
    create_alert_server,
    validate_alertmanager_payload,
)


def _payload() -> dict[str, Any]:
    return {
        "version": "4",
        "groupKey": "collector",
        "status": "firing",
        "receiver": "greenfield-audit",
        "alerts": [
            {
                "status": "firing",
                "labels": {"alertname": "CollectorStale", "collector_id": "btcusdt"},
                "annotations": {"summary": "collector stale"},
                "startsAt": "2026-08-22T00:00:00Z",
            }
        ],
    }


def test_processor_fsyncs_receipt_before_successful_forward(tmp_path: Path) -> None:
    observed: list[tuple[Mapping[str, Any], str]] = []

    def forward(payload: Mapping[str, Any], event_id: str) -> None:
        files = list(tmp_path.glob("*.jsonl"))
        assert len(files) == 1
        assert "alertmanager_receipt" in files[0].read_text(encoding="utf-8")
        observed.append((payload, event_id))

    processor = AlertDeliveryProcessor(
        AlertJournal(tmp_path), forwarder=forward, wall_clock_ns=lambda: 1_777_000_000_000_000_000
    )
    result = processor.process(_payload())

    records = [json.loads(line) for line in result.journal_path.read_text().splitlines()]
    assert result.forwarded is True
    assert result.alert_count == 1
    assert observed[0][1] == result.event_id
    assert [record["record_type"] for record in records] == [
        "alertmanager_receipt",
        "forward_success",
    ]


def test_forward_failure_is_journaled_and_raised(tmp_path: Path) -> None:
    def fail(_payload: Mapping[str, Any], _event_id: str) -> None:
        raise ForwardingError("external webhook transport failed (TimeoutError)")

    processor = AlertDeliveryProcessor(
        AlertJournal(tmp_path), forwarder=fail, wall_clock_ns=lambda: 1_777_000_000_000_000_000
    )

    with pytest.raises(ForwardingError, match="transport failed"):
        processor.process(_payload())

    records = [
        json.loads(line)
        for line in next(tmp_path.glob("*.jsonl")).read_text().splitlines()
    ]
    assert [record["record_type"] for record in records] == [
        "alertmanager_receipt",
        "forward_failure",
    ]
    assert "http" not in records[1]["error"].lower()


@pytest.mark.parametrize(
    "payload",
    [None, [], {}, {"status": "unknown", "alerts": []}, {"status": "firing", "alerts": [1]}],
)
def test_validation_rejects_non_alertmanager_payload(payload: Any) -> None:
    with pytest.raises(InvalidAlertPayload):
        validate_alertmanager_payload(payload)


def test_forwarder_requires_https() -> None:
    with pytest.raises(ValueError, match="HTTPS"):
        HttpsWebhookForwarder("http://example.com/hook")


def test_https_forwarder_exposes_event_id_in_header_and_json(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    observed: dict[str, Any] = {}

    class Response:
        status = 200

        def __enter__(self) -> Response:
            return self

        def __exit__(self, *_args: object) -> None:
            return None

    def open_request(request: urllib.request.Request, *, timeout: float) -> Response:
        observed["request"] = request
        observed["timeout"] = timeout
        return Response()

    monkeypatch.setattr(urllib.request, "urlopen", open_request)
    payload = _payload()
    event_id = "a" * 64

    HttpsWebhookForwarder("https://example.com/hook", timeout_secs=3.0)(
        payload, event_id
    )

    request = observed["request"]
    assert isinstance(request, urllib.request.Request)
    assert request.get_header("X-greenfield-event-id") == event_id
    assert observed["timeout"] == 3.0
    forwarded = json.loads(request.data)
    assert forwarded["greenfield"] == {"schema_version": 1, "event_id": event_id}
    assert "greenfield" not in payload


def test_alertmanager_cannot_spoof_reserved_delivery_metadata() -> None:
    payload = _payload()
    payload["greenfield"] = {"event_id": "spoofed"}

    with pytest.raises(InvalidAlertPayload, match="reserved"):
        validate_alertmanager_payload(payload)


def test_http_server_exposes_health_metrics_and_durable_post(tmp_path: Path) -> None:
    processor = AlertDeliveryProcessor(AlertJournal(tmp_path))
    server = create_alert_server(("127.0.0.1", 0), processor)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base_url = f"http://127.0.0.1:{server.server_port}"
    try:
        with urllib.request.urlopen(f"{base_url}/health") as response:
            assert response.status == 200
        request = urllib.request.Request(
            f"{base_url}/alerts",
            data=json.dumps(_payload()).encode(),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(request) as response:
            assert response.status == 202
            assert json.loads(response.read())["stored"] is True
        with urllib.request.urlopen(f"{base_url}/metrics") as response:
            metrics = response.read().decode()
            assert "greenfield_alert_receiver_received_webhooks_total 1" in metrics
            assert "greenfield_alert_receiver_received_alerts_total 1" in metrics
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def test_http_server_rejects_oversized_body(tmp_path: Path) -> None:
    processor = AlertDeliveryProcessor(AlertJournal(tmp_path))
    server = create_alert_server(("127.0.0.1", 0), processor, max_body_bytes=4)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        request = urllib.request.Request(
            f"http://127.0.0.1:{server.server_port}/alerts",
            data=b"12345",
            method="POST",
        )
        with pytest.raises(urllib.error.HTTPError) as error:
            urllib.request.urlopen(request)
        assert error.value.code == 413
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)
