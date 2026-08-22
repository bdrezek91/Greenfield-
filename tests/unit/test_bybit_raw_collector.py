"""The direct collector stores raw messages before validating stream state."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from src.data.bybit_raw_collector import RawBybitCollector
from src.data.raw_store import load_raw_events


class FakeWS:
    def __init__(self) -> None:
        self.sent: list[str] = []
        self.close_count = 0

    def send(self, value: str) -> None:
        self.sent.append(value)

    def close(self) -> None:
        self.close_count += 1


def _book_message(message_type: str, update_id: int, sequence: int) -> str:
    return json.dumps(
        {
            "topic": "orderbook.50.BTCUSDT",
            "type": message_type,
            "ts": 1_700_000_000_000 + update_id,
            "data": {
                "s": "BTCUSDT",
                "b": [["100", str(update_id)]],
                "a": [["101", "1"]],
                "u": update_id,
                "seq": sequence,
            },
        },
        separators=(",", ":"),
    )


def test_topics_cover_lossless_phase_one_streams_for_every_symbol(tmp_path: Path) -> None:
    collector = RawBybitCollector(("BTCUSDT", "ETHUSDT"), tmp_path)

    assert collector.topics == (
        "orderbook.50.BTCUSDT",
        "publicTrade.BTCUSDT",
        "allLiquidation.BTCUSDT",
        "tickers.BTCUSDT",
        "orderbook.50.ETHUSDT",
        "publicTrade.ETHUSDT",
        "allLiquidation.ETHUSDT",
        "tickers.ETHUSDT",
    )


def test_collector_id_is_safe_for_health_file_paths(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="collector_id"):
        RawBybitCollector(("BTCUSDT",), tmp_path, collector_id="../escape")


def test_open_subscribes_all_topics_and_publishes_health(tmp_path: Path) -> None:
    collector = RawBybitCollector(("BTCUSDT",), tmp_path, ping_interval_secs=999)
    collector._prepare_connection()
    ws = FakeWS()

    collector._on_open(ws)
    request = json.loads(ws.sent[0])

    assert request["op"] == "subscribe"
    assert request["args"] == list(collector.topics)
    assert (tmp_path / "health" / "bybit-linear-all.json").is_file()
    collector._connection_stop.set()


def test_sequence_gap_is_raw_queued_then_connection_is_closed(tmp_path: Path) -> None:
    collector = RawBybitCollector(("BTCUSDT",), tmp_path)
    collector._prepare_connection()
    ws = FakeWS()
    collector._active_ws = ws

    collector.handle_raw_message(_book_message("snapshot", 10, 100))
    collector.handle_raw_message(_book_message("delta", 12, 102))

    snapshot = collector.health.snapshot(queue_depth=collector._queue.qsize())
    assert collector._queue.qsize() == 2
    assert snapshot["sequence_uncertainty_count"] == 1
    assert snapshot["dropped_event_count"] == 0
    assert ws.close_count == 1


def test_queue_overflow_stops_instead_of_silently_dropping(tmp_path: Path) -> None:
    collector = RawBybitCollector(("BTCUSDT",), tmp_path, queue_capacity=1)
    collector._prepare_connection()

    collector.handle_raw_message('{"success":true,"op":"subscribe"}')
    collector.handle_raw_message('{"success":true,"op":"pong"}')

    snapshot = collector.health.snapshot()
    assert snapshot["dropped_event_count"] == 1
    assert snapshot["status"] == "failed"
    assert collector._shutdown.is_set()


def test_storage_reserve_breach_stops_before_subscribing(tmp_path: Path) -> None:
    gib = 1024**3
    collector = RawBybitCollector(
        ("BTCUSDT",),
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
    assert snapshot["dropped_event_count"] == 0
    assert "storage reserve breached" in snapshot["last_error"]
    assert snapshot["storage_runtime_minimum_free_bytes"] == 5 * gib


def test_runtime_storage_breach_drains_already_queued_event(tmp_path: Path) -> None:
    gib = 1024**3
    collector = RawBybitCollector(
        ("BTCUSDT",),
        tmp_path,
        health_interval_secs=60,
        minimum_runtime_free_gib=5,
        disk_usage=lambda _: SimpleNamespace(total=100 * gib, used=96 * gib, free=4 * gib),
    )
    collector._prepare_connection()
    collector._start_background_workers()
    payload = _book_message("snapshot", 10, 100)
    collector.handle_raw_message(payload)

    assert not collector._enforce_storage_reserve()
    collector.stop()

    events = load_raw_events(tmp_path, channel="orderbook", symbol="BTCUSDT")
    assert [event.payload_text for event in events] == [payload]
    assert collector.health.snapshot()["status"] == "failed"


def test_writer_drains_queue_and_persists_exact_payload_on_stop(tmp_path: Path) -> None:
    collector = RawBybitCollector(
        ("BTCUSDT",),
        tmp_path,
        flush_interval_secs=60,
        health_interval_secs=60,
    )
    collector._prepare_connection()
    collector._start_background_workers()
    payload = _book_message("snapshot", 10, 100)
    collector.handle_raw_message(payload)

    collector.stop()

    events = load_raw_events(tmp_path, channel="orderbook", symbol="BTCUSDT")
    assert len(events) == 1
    assert events[0].payload_text == payload
    health = collector.health.snapshot()
    assert health["events_written"] == 1
    assert health["status"] == "stopped"


def test_non_utf8_message_fails_closed(tmp_path: Path) -> None:
    collector = RawBybitCollector(("BTCUSDT",), tmp_path)
    collector._prepare_connection()

    collector.handle_raw_message(b"\xff")

    assert collector.health.snapshot()["dropped_event_count"] == 1
    assert collector._shutdown.is_set()


def test_ping_loop_sends_bybit_json_ping(tmp_path: Path) -> None:
    collector = RawBybitCollector(("BTCUSDT",), tmp_path, ping_interval_secs=0.001)
    ws = FakeWS()

    class StopAfterOnePing:
        def __init__(self) -> None:
            self.calls = 0

        def wait(self, timeout: float) -> bool:
            self.calls += 1
            return self.calls > 1

    collector._ping_loop(ws, StopAfterOnePing())

    assert {json.loads(value).get("op") for value in ws.sent} == {"ping"}
