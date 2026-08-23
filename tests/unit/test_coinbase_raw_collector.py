"""The direct Coinbase collector stores raw messages before validating L2 state."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from src.data.coinbase_raw_collector import RawCoinbaseCollector
from src.data.raw_store import load_raw_events


class FakeWS:
    def __init__(self) -> None:
        self.sent: list[str] = []
        self.close_count = 0

    def send(self, value: str) -> None:
        self.sent.append(value)

    def close(self) -> None:
        self.close_count += 1


def _msg(channel: str, sequence: int, *, product_id: str | None = "BTC-USD") -> str:
    events = [{"type": "update", "product_id": product_id, "updates": []}] if product_id else []
    return json.dumps(
        {
            "channel": channel,
            "timestamp": "2026-08-23T00:00:00Z",
            "sequence_num": sequence,
            "events": events,
        },
        separators=(",", ":"),
    )


def _level2_message(message_type: str, sequence: int) -> str:
    return json.dumps(
        {
            "channel": "l2_data",
            "timestamp": "2026-08-23T00:00:00Z",
            "sequence_num": sequence,
            "events": [
                {
                    "type": message_type,
                    "product_id": "BTC-USD",
                    "updates": [
                        {
                            "side": "bid",
                            "event_time": "2026-08-23T00:00:00Z",
                            "price_level": "100",
                            "new_quantity": "1",
                        }
                    ],
                }
            ],
        },
        separators=(",", ":"),
    )


def test_health_reports_sequence_continuity_as_verified(tmp_path: Path) -> None:
    """Cycle 8: a working connection-global sequence gate is wired - see
    the module's "SEQUENCE CONTINUITY" note."""
    collector = RawCoinbaseCollector(("BTC-USD",), tmp_path)
    assert collector.health.snapshot()["sequence_continuity_verified"] is True


def test_subscribe_messages_cover_every_channel(tmp_path: Path) -> None:
    collector = RawCoinbaseCollector(("BTC-USD", "ETH-USD"), tmp_path)

    assert collector.subscribe_messages == (
        {"type": "subscribe", "product_ids": ["BTC-USD", "ETH-USD"], "channel": "level2"},
        {
            "type": "subscribe",
            "product_ids": ["BTC-USD", "ETH-USD"],
            "channel": "market_trades",
        },
        {"type": "subscribe", "product_ids": ["BTC-USD", "ETH-USD"], "channel": "ticker"},
    )


def test_collector_id_is_safe_for_health_file_paths(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="collector_id"):
        RawCoinbaseCollector(("BTC-USD",), tmp_path, collector_id="../escape")


def test_ping_timeout_must_be_smaller_than_interval(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="ping timeout"):
        RawCoinbaseCollector(
            ("BTC-USD",), tmp_path, ping_interval_secs=10, ping_timeout_secs=10
        )


def test_open_subscribes_all_channels_and_publishes_health(tmp_path: Path) -> None:
    collector = RawCoinbaseCollector(("BTC-USD",), tmp_path)
    collector._prepare_connection()
    ws = FakeWS()

    collector._on_open(ws)
    sent = [json.loads(value) for value in ws.sent]

    assert sent == list(collector.subscribe_messages)
    assert (tmp_path / "health" / "coinbase-spot-all.json").is_file()
    collector._connection_stop.set()


def test_valid_sequence_across_channels_and_products_does_not_flag_uncertainty(
    tmp_path: Path,
) -> None:
    """The real, probed Coinbase behavior: one counter shared by every
    channel and product on the connection - a realistic interleaved stream
    must not be mistaken for a gap."""
    collector = RawCoinbaseCollector(("BTC-USD", "ETH-USD"), tmp_path)
    collector._prepare_connection()
    ws = FakeWS()
    collector._active_ws = ws

    collector.handle_raw_message(_msg("subscriptions", 100, product_id=None))
    collector.handle_raw_message(_msg("l2_data", 101, product_id="BTC-USD"))
    collector.handle_raw_message(_msg("market_trades", 102, product_id="ETH-USD"))
    collector.handle_raw_message(_msg("ticker", 103, product_id="BTC-USD"))
    collector.handle_raw_message(_msg("l2_data", 104, product_id="ETH-USD"))

    snapshot = collector.health.snapshot(queue_depth=collector._queue.qsize())
    assert collector._queue.qsize() == 5
    assert snapshot["sequence_uncertainty_count"] == 0
    assert snapshot["status"] != "sequence_uncertain"
    assert ws.close_count == 0


def test_real_sequence_gap_is_detected_forces_reconnect_but_still_queues_raw(
    tmp_path: Path,
) -> None:
    collector = RawCoinbaseCollector(("BTC-USD",), tmp_path)
    collector._prepare_connection()
    ws = FakeWS()
    collector._active_ws = ws

    collector.handle_raw_message(_level2_message("snapshot", 10))
    collector.handle_raw_message(_level2_message("update", 13))  # nothing explains 11, 12

    snapshot = collector.health.snapshot(queue_depth=collector._queue.qsize())
    # fail-closed on continuity, but raw capture is never compromised: both
    # messages this process actually received are still queued/written
    assert collector._queue.qsize() == 2
    assert snapshot["sequence_uncertainty_count"] == 1
    assert snapshot["status"] == "sequence_uncertain"
    assert ws.close_count == 1


def test_duplicate_sequence_num_is_detected_and_forces_reconnect(tmp_path: Path) -> None:
    collector = RawCoinbaseCollector(("BTC-USD",), tmp_path)
    collector._prepare_connection()
    ws = FakeWS()
    collector._active_ws = ws

    collector.handle_raw_message(_msg("l2_data", 10))
    collector.handle_raw_message(_msg("market_trades", 11))
    collector.handle_raw_message(_msg("ticker", 11))  # duplicate

    snapshot = collector.health.snapshot(queue_depth=collector._queue.qsize())
    assert collector._queue.qsize() == 3
    assert snapshot["sequence_uncertainty_count"] == 1
    assert ws.close_count == 1


def test_sequence_rollback_is_detected_and_forces_reconnect(tmp_path: Path) -> None:
    collector = RawCoinbaseCollector(("BTC-USD",), tmp_path)
    collector._prepare_connection()
    ws = FakeWS()
    collector._active_ws = ws

    collector.handle_raw_message(_msg("l2_data", 50))
    collector.handle_raw_message(_msg("market_trades", 51))
    collector.handle_raw_message(_msg("ticker", 20))  # rollback

    snapshot = collector.health.snapshot(queue_depth=collector._queue.qsize())
    assert collector._queue.qsize() == 3
    assert snapshot["sequence_uncertainty_count"] == 1
    assert ws.close_count == 1


def test_sequence_uncertain_state_is_not_rechecked_until_next_connection(
    tmp_path: Path,
) -> None:
    """Fail-closed after continuity loss: once uncertain, further messages
    on the same (about-to-be-closed) connection are still captured but no
    longer re-evaluated against the now-untrustworthy counter."""
    collector = RawCoinbaseCollector(("BTC-USD",), tmp_path)
    collector._prepare_connection()
    ws = FakeWS()
    collector._active_ws = ws
    collector.handle_raw_message(_msg("l2_data", 10))
    collector.handle_raw_message(_msg("l2_data", 13))  # triggers uncertainty
    assert collector._sequence_uncertain is True

    collector.handle_raw_message(_msg("l2_data", 999))  # would also "gap" - must not re-raise

    snapshot = collector.health.snapshot(queue_depth=collector._queue.qsize())
    assert collector._queue.qsize() == 3
    assert snapshot["sequence_uncertainty_count"] == 1  # not incremented again


def test_prepare_connection_resets_sequence_gate_for_a_fresh_connection(
    tmp_path: Path,
) -> None:
    """A reconnect gets a clean slate: neither the stale connection_id nor
    the sequence_uncertain flag leaks into the new connection."""
    collector = RawCoinbaseCollector(("BTC-USD",), tmp_path)
    collector._prepare_connection()
    ws = FakeWS()
    collector._active_ws = ws
    collector.handle_raw_message(_msg("l2_data", 10))
    collector.handle_raw_message(_msg("l2_data", 13))  # triggers uncertainty
    assert collector._sequence_uncertain is True

    collector._prepare_connection()  # simulates run_forever()'s reconnect loop

    assert collector._sequence_uncertain is False
    assert collector._sequence_gate.connection_id is None
    assert collector._sequence_gate.last_sequence is None
    # a low sequence_num on the new connection must not be a "rollback"
    new_ws = FakeWS()
    collector._active_ws = new_ws
    collector.handle_raw_message(_msg("l2_data", 3))
    assert collector.health.snapshot()["sequence_uncertainty_count"] == 1  # unchanged
    assert new_ws.close_count == 0


def test_sequence_gap_updates_health_json_and_prometheus_output(tmp_path: Path) -> None:
    collector = RawCoinbaseCollector(("BTC-USD",), tmp_path)
    collector._prepare_connection()
    ws = FakeWS()
    collector._active_ws = ws

    collector.handle_raw_message(_msg("l2_data", 10))
    collector.handle_raw_message(_msg("l2_data", 99))  # gap

    health_path = tmp_path / "health" / "coinbase-spot-all.json"
    metrics_path = health_path.with_suffix(".prom")
    payload = json.loads(health_path.read_text(encoding="utf-8"))
    assert payload["sequence_uncertainty_count"] == 1
    assert payload["status"] == "sequence_uncertain"
    assert payload["sequence_continuity_verified"] is True
    metrics = metrics_path.read_text(encoding="utf-8")
    assert "greenfield_collector_sequence_uncertainty_count" in metrics
    assert 'greenfield_collector_sequence_continuity_verified{exchange="coinbase"' in metrics


def test_multi_product_message_is_captured_without_gating(tmp_path: Path) -> None:
    collector = RawCoinbaseCollector(("BTC-USD",), tmp_path)
    collector._prepare_connection()
    multi_payload = json.dumps(
        {
            "channel": "l2_data",
            "timestamp": "2026-08-23T00:00:00Z",
            "sequence_num": 0,
            "events": [
                {"type": "snapshot", "product_id": "BTC-USD", "updates": []},
                {"type": "snapshot", "product_id": "ETH-USD", "updates": []},
            ],
        },
        separators=(",", ":"),
    )

    collector.handle_raw_message(multi_payload)

    assert collector.health.snapshot()["sequence_uncertainty_count"] == 0
    assert collector._queue.qsize() == 1


def test_queue_overflow_stops_instead_of_silently_dropping(tmp_path: Path) -> None:
    collector = RawCoinbaseCollector(("BTC-USD",), tmp_path, queue_capacity=1)
    collector._prepare_connection()

    collector.handle_raw_message(_level2_message("snapshot", 1))
    collector.handle_raw_message(_level2_message("snapshot", 2))

    snapshot = collector.health.snapshot()
    assert snapshot["dropped_event_count"] == 1
    assert snapshot["status"] == "failed"
    assert collector._shutdown.is_set()


def test_storage_reserve_breach_stops_before_subscribing(tmp_path: Path) -> None:
    gib = 1024**3
    collector = RawCoinbaseCollector(
        ("BTC-USD",),
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
    collector = RawCoinbaseCollector(
        ("BTC-USD",), tmp_path, flush_interval_secs=60, health_interval_secs=60
    )
    collector._prepare_connection()
    collector._start_background_workers()
    payload = _level2_message("snapshot", 1)
    collector.handle_raw_message(payload)

    collector.stop()

    events = load_raw_events(tmp_path, channel="orderbook", symbol="BTC-USD")
    assert len(events) == 1
    assert events[0].payload_text == payload
    health = collector.health.snapshot()
    assert health["events_written"] == 1
    assert health["status"] == "stopped"


def test_non_utf8_message_fails_closed(tmp_path: Path) -> None:
    collector = RawCoinbaseCollector(("BTC-USD",), tmp_path)
    collector._prepare_connection()

    collector.handle_raw_message(b"\xff")

    assert collector.health.snapshot()["dropped_event_count"] == 1
    assert collector._shutdown.is_set()
