"""The direct OKX collector stores raw messages before validating book state."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from src.data.okx_raw_collector import RawOkxCollector
from src.data.raw_store import load_raw_events


class FakeWS:
    def __init__(self) -> None:
        self.sent: list[str] = []
        self.close_count = 0

    def send(self, value: str) -> None:
        self.sent.append(value)

    def close(self) -> None:
        self.close_count += 1


def _book_message(action: str, sequence: int, previous: int) -> str:
    return json.dumps(
        {
            "arg": {"channel": "books", "instId": "BTC-USDT-SWAP"},
            "action": action,
            "data": [
                {
                    "asks": [],
                    "bids": [["100", "1", "0", "1"]],
                    "ts": "1700000000000",
                    "seqId": sequence,
                    "prevSeqId": previous,
                    "checksum": 0,
                }
            ],
        },
        separators=(",", ":"),
    )


def test_subscribe_args_cover_every_channel_for_every_inst_id(tmp_path: Path) -> None:
    collector = RawOkxCollector(("BTC-USDT-SWAP", "ETH-USDT-SWAP"), tmp_path)

    assert collector.subscribe_args == (
        {"channel": "books", "instId": "BTC-USDT-SWAP"},
        {"channel": "trades", "instId": "BTC-USDT-SWAP"},
        {"channel": "tickers", "instId": "BTC-USDT-SWAP"},
        {"channel": "books", "instId": "ETH-USDT-SWAP"},
        {"channel": "trades", "instId": "ETH-USDT-SWAP"},
        {"channel": "tickers", "instId": "ETH-USDT-SWAP"},
    )


def test_collector_id_is_safe_for_health_file_paths(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="collector_id"):
        RawOkxCollector(("BTC-USDT-SWAP",), tmp_path, collector_id="../escape")


def test_open_subscribes_all_args_and_publishes_health(tmp_path: Path) -> None:
    collector = RawOkxCollector(("BTC-USDT-SWAP",), tmp_path, ping_interval_secs=999)
    collector._prepare_connection()
    ws = FakeWS()

    collector._on_open(ws)
    request = json.loads(ws.sent[0])

    assert request["op"] == "subscribe"
    assert request["args"] == list(collector.subscribe_args)
    assert (tmp_path / "health" / "okx-swap-all.json").is_file()
    collector._connection_stop.set()


def test_plain_text_pong_is_ignored_not_enveloped(tmp_path: Path) -> None:
    collector = RawOkxCollector(("BTC-USDT-SWAP",), tmp_path)
    collector._prepare_connection()

    collector.handle_raw_message("pong")

    assert collector._queue.qsize() == 0
    assert collector.health.snapshot()["dropped_event_count"] == 0


def test_sequence_gap_is_raw_queued_then_connection_is_closed(tmp_path: Path) -> None:
    collector = RawOkxCollector(("BTC-USDT-SWAP",), tmp_path)
    collector._prepare_connection()
    ws = FakeWS()
    collector._active_ws = ws

    collector.handle_raw_message(_book_message("snapshot", 100, -1))
    collector.handle_raw_message(_book_message("update", 105, 104))  # gap: expected prev=100

    snapshot = collector.health.snapshot(queue_depth=collector._queue.qsize())
    assert collector._queue.qsize() == 2
    assert snapshot["sequence_uncertainty_count"] == 1
    assert snapshot["dropped_event_count"] == 0
    assert ws.close_count == 1


def test_queue_overflow_stops_instead_of_silently_dropping(tmp_path: Path) -> None:
    collector = RawOkxCollector(("BTC-USDT-SWAP",), tmp_path, queue_capacity=1)
    collector._prepare_connection()

    collector.handle_raw_message(_book_message("snapshot", 1, -1))
    collector.handle_raw_message(_book_message("snapshot", 2, -1))

    snapshot = collector.health.snapshot()
    assert snapshot["dropped_event_count"] == 1
    assert snapshot["status"] == "failed"
    assert collector._shutdown.is_set()


def test_storage_reserve_breach_stops_before_subscribing(tmp_path: Path) -> None:
    gib = 1024**3
    collector = RawOkxCollector(
        ("BTC-USDT-SWAP",),
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
    collector = RawOkxCollector(
        ("BTC-USDT-SWAP",), tmp_path, flush_interval_secs=60, health_interval_secs=60
    )
    collector._prepare_connection()
    collector._start_background_workers()
    payload = _book_message("snapshot", 1, -1)
    collector.handle_raw_message(payload)

    collector.stop()

    events = load_raw_events(tmp_path, channel="orderbook", symbol="BTC-USDT-SWAP")
    assert len(events) == 1
    assert events[0].payload_text == payload
    health = collector.health.snapshot()
    assert health["events_written"] == 1
    assert health["status"] == "stopped"


def test_request_stop_wakes_connection_without_finalizing_workers(tmp_path: Path) -> None:
    collector = RawOkxCollector(("BTC-USDT-SWAP",), tmp_path)
    ws = FakeWS()
    collector._active_ws = ws

    collector.request_stop()

    assert collector._shutdown.is_set()
    assert collector._connection_stop.is_set()
    assert ws.close_count == 1
    assert collector.health.snapshot()["status"] == "starting"


def test_non_utf8_message_fails_closed(tmp_path: Path) -> None:
    collector = RawOkxCollector(("BTC-USDT-SWAP",), tmp_path)
    collector._prepare_connection()

    collector.handle_raw_message(b"\xff")

    assert collector.health.snapshot()["dropped_event_count"] == 1
    assert collector._shutdown.is_set()


def test_ping_loop_sends_plain_text_ping(tmp_path: Path) -> None:
    collector = RawOkxCollector(("BTC-USDT-SWAP",), tmp_path, ping_interval_secs=0.001)
    ws = FakeWS()

    class StopAfterOnePing:
        def __init__(self) -> None:
            self.calls = 0

        def wait(self, timeout: float) -> bool:
            self.calls += 1
            return self.calls > 1

    collector._ping_loop(ws, StopAfterOnePing())

    assert ws.sent == ["ping"]
