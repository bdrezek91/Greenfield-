"""The direct Deribit collector stores raw messages before validating
per-instrument book continuity (`src.data.deribit_adapter.
DeribitBookSequenceGate`)."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from src.data.deribit_raw_collector import RawDeribitCollector
from src.data.raw_store import load_raw_events


class FakeWS:
    def __init__(self) -> None:
        self.sent: list[str] = []
        self.close_count = 0

    def send(self, value: str) -> None:
        self.sent.append(value)

    def close(self) -> None:
        self.close_count += 1


def _book_message(
    message_type: str, change_id: int, previous: int | None = None, *, instrument: str
) -> str:
    data = {
        "type": message_type,
        "timestamp": 1_700_000_000_000,
        "instrument_name": instrument,
        "change_id": change_id,
        "bids": [["new", 100.0, 1.0]],
        "asks": [],
    }
    if previous is not None:
        data["prev_change_id"] = previous
    return json.dumps(
        {
            "jsonrpc": "2.0",
            "method": "subscription",
            "params": {"channel": f"book.{instrument}.100ms", "data": data},
        },
        separators=(",", ":"),
    )


def _heartbeat_test_request() -> str:
    return json.dumps(
        {"jsonrpc": "2.0", "method": "heartbeat", "params": {"type": "test_request"}},
        separators=(",", ":"),
    )


def test_subscribe_channels_cover_every_kind_for_every_instrument(tmp_path: Path) -> None:
    collector = RawDeribitCollector(("BTC-PERPETUAL", "ETH-PERPETUAL"), tmp_path)

    assert collector.subscribe_channels == (
        "book.BTC-PERPETUAL.100ms",
        "trades.BTC-PERPETUAL.100ms",
        "ticker.BTC-PERPETUAL.100ms",
        "book.ETH-PERPETUAL.100ms",
        "trades.ETH-PERPETUAL.100ms",
        "ticker.ETH-PERPETUAL.100ms",
    )


def test_collector_id_is_safe_for_health_file_paths(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="collector_id"):
        RawDeribitCollector(("BTC-PERPETUAL",), tmp_path, collector_id="../escape")


def test_heartbeat_interval_must_be_at_least_ten_seconds(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="heartbeat interval"):
        RawDeribitCollector(("BTC-PERPETUAL",), tmp_path, heartbeat_interval_secs=5)


def test_open_sets_heartbeat_then_subscribes_and_publishes_health(tmp_path: Path) -> None:
    collector = RawDeribitCollector(("BTC-PERPETUAL",), tmp_path)
    collector._prepare_connection()
    ws = FakeWS()

    collector._on_open(ws)
    heartbeat_request = json.loads(ws.sent[0])
    subscribe_request = json.loads(ws.sent[1])

    assert heartbeat_request["method"] == "public/set_heartbeat"
    assert heartbeat_request["params"]["interval"] == 30
    assert subscribe_request["method"] == "public/subscribe"
    assert subscribe_request["params"]["channels"] == list(collector.subscribe_channels)
    assert (tmp_path / "health" / "deribit-future-all.json").is_file()


def test_heartbeat_test_request_gets_a_public_test_reply(tmp_path: Path) -> None:
    collector = RawDeribitCollector(("BTC-PERPETUAL",), tmp_path)
    collector._prepare_connection()
    ws = FakeWS()
    collector._active_ws = ws

    collector.handle_raw_message(_heartbeat_test_request())

    assert collector._queue.qsize() == 1  # heartbeat is itself raw-captured
    reply = json.loads(ws.sent[0])
    assert reply == {"jsonrpc": "2.0", "method": "public/test", "params": {}}


def test_plain_heartbeat_info_message_gets_no_reply(tmp_path: Path) -> None:
    collector = RawDeribitCollector(("BTC-PERPETUAL",), tmp_path)
    collector._prepare_connection()
    ws = FakeWS()
    collector._active_ws = ws

    collector.handle_raw_message(
        json.dumps({"jsonrpc": "2.0", "method": "heartbeat", "params": {"type": "heartbeat"}})
    )

    assert ws.sent == []


def test_valid_snapshot_then_change_does_not_flag_uncertainty(tmp_path: Path) -> None:
    collector = RawDeribitCollector(("BTC-PERPETUAL",), tmp_path)
    collector._prepare_connection()
    ws = FakeWS()
    collector._active_ws = ws

    collector.handle_raw_message(_book_message("snapshot", 100, instrument="BTC-PERPETUAL"))
    collector.handle_raw_message(_book_message("change", 101, 100, instrument="BTC-PERPETUAL"))

    snapshot = collector.health.snapshot(queue_depth=collector._queue.qsize())
    assert collector._queue.qsize() == 2
    assert snapshot["sequence_uncertainty_count"] == 0
    assert ws.close_count == 0


def test_sequence_gap_is_raw_queued_then_connection_is_closed(tmp_path: Path) -> None:
    collector = RawDeribitCollector(("BTC-PERPETUAL",), tmp_path)
    collector._prepare_connection()
    ws = FakeWS()
    collector._active_ws = ws

    collector.handle_raw_message(_book_message("snapshot", 100, instrument="BTC-PERPETUAL"))
    collector.handle_raw_message(_book_message("change", 105, 104, instrument="BTC-PERPETUAL"))

    snapshot = collector.health.snapshot(queue_depth=collector._queue.qsize())
    assert collector._queue.qsize() == 2
    assert snapshot["sequence_uncertainty_count"] == 1
    assert snapshot["dropped_event_count"] == 0
    assert ws.close_count == 1


def test_other_instruments_are_unaffected_but_connection_flag_is_shared(tmp_path: Path) -> None:
    collector = RawDeribitCollector(("BTC-PERPETUAL", "ETH-PERPETUAL"), tmp_path)
    collector._prepare_connection()
    ws = FakeWS()
    collector._active_ws = ws

    collector.handle_raw_message(_book_message("snapshot", 100, instrument="BTC-PERPETUAL"))
    collector.handle_raw_message(_book_message("change", 200, 150, instrument="BTC-PERPETUAL"))
    collector.handle_raw_message(_book_message("snapshot", 10, instrument="ETH-PERPETUAL"))
    collector.handle_raw_message(_book_message("change", 11, 10, instrument="ETH-PERPETUAL"))

    assert collector._queue.qsize() == 4
    assert ws.close_count == 1


def test_prepare_connection_resets_book_gates_for_a_fresh_connection(tmp_path: Path) -> None:
    collector = RawDeribitCollector(("BTC-PERPETUAL",), tmp_path)
    collector._prepare_connection()
    ws = FakeWS()
    collector._active_ws = ws
    collector.handle_raw_message(_book_message("snapshot", 100, instrument="BTC-PERPETUAL"))
    collector.handle_raw_message(_book_message("change", 200, 150, instrument="BTC-PERPETUAL"))
    assert collector._sequence_uncertain is True

    collector._prepare_connection()

    assert collector._sequence_uncertain is False
    assert collector._books["BTC-PERPETUAL"].change_id is None
    new_ws = FakeWS()
    collector._active_ws = new_ws
    collector.handle_raw_message(_book_message("snapshot", 5, instrument="BTC-PERPETUAL"))
    assert collector.health.snapshot()["sequence_uncertainty_count"] == 1  # unchanged
    assert new_ws.close_count == 0


def test_queue_overflow_stops_instead_of_silently_dropping(tmp_path: Path) -> None:
    collector = RawDeribitCollector(("BTC-PERPETUAL",), tmp_path, queue_capacity=1)
    collector._prepare_connection()

    collector.handle_raw_message(_book_message("snapshot", 1, instrument="BTC-PERPETUAL"))
    collector.handle_raw_message(_book_message("snapshot", 2, instrument="BTC-PERPETUAL"))

    snapshot = collector.health.snapshot()
    assert snapshot["dropped_event_count"] == 1
    assert snapshot["status"] == "failed"
    assert collector._shutdown.is_set()


def test_storage_reserve_breach_stops_before_subscribing(tmp_path: Path) -> None:
    gib = 1024**3
    collector = RawDeribitCollector(
        ("BTC-PERPETUAL",),
        tmp_path,
        minimum_runtime_free_gib=5,
        disk_usage=lambda _: SimpleNamespace(total=100 * gib, used=96 * gib, free=4 * gib),
    )
    collector._prepare_connection()
    ws = FakeWS()
    collector._active_ws = ws

    collector._on_open(ws)

    snapshot = collector.health.snapshot()
    assert ws.sent == []
    assert ws.close_count == 1
    assert collector._shutdown.is_set()
    assert snapshot["status"] == "failed"
    assert "storage reserve breached" in snapshot["last_error"]


def test_writer_drains_queue_and_persists_exact_payload_on_stop(tmp_path: Path) -> None:
    collector = RawDeribitCollector(
        ("BTC-PERPETUAL",), tmp_path, flush_interval_secs=60, health_interval_secs=60
    )
    collector._prepare_connection()
    collector._start_background_workers()
    payload = _book_message("snapshot", 1, instrument="BTC-PERPETUAL")
    collector.handle_raw_message(payload)

    collector.stop()

    events = load_raw_events(tmp_path, channel="orderbook", symbol="BTC-PERPETUAL")
    assert len(events) == 1
    assert events[0].payload_text == payload
    health = collector.health.snapshot()
    assert health["events_written"] == 1
    assert health["status"] == "stopped"


def test_non_utf8_message_fails_closed(tmp_path: Path) -> None:
    collector = RawDeribitCollector(("BTC-PERPETUAL",), tmp_path)
    collector._prepare_connection()

    collector.handle_raw_message(b"\xff")

    assert collector.health.snapshot()["dropped_event_count"] == 1
    assert collector._shutdown.is_set()


def test_health_reports_sequence_continuity_as_verified(tmp_path: Path) -> None:
    collector = RawDeribitCollector(("BTC-PERPETUAL",), tmp_path)
    assert collector.health.snapshot()["sequence_continuity_verified"] is True
