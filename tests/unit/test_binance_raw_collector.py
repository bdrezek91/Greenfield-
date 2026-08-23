"""The direct Binance collector stores raw messages before validating
per-symbol, REST-snapshot-bridged depth continuity
(`src.data.binance_adapter.BinanceDepthSequenceGate`)."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from src.data.binance_raw_collector import RawBinanceCollector
from src.data.raw_store import load_raw_events


class FakeWS:
    def __init__(self) -> None:
        self.sent: list[str] = []
        self.close_count = 0

    def send(self, value: str) -> None:
        self.sent.append(value)

    def close(self) -> None:
        self.close_count += 1


def _fake_fetcher(snapshot_ids: dict[str, int]):
    def fetch(symbol: str) -> int:
        return snapshot_ids[symbol]

    return fetch


def _failing_fetcher(symbol: str) -> int:
    raise ConnectionError("simulated network failure")


def _depth_message(
    final_update_id: int,
    previous_final_update_id: int,
    *,
    first_update_id: int | None = None,
    symbol: str = "BTCUSDT",
) -> str:
    return json.dumps(
        {
            "stream": f"{symbol.lower()}@depth@100ms",
            "data": {
                "e": "depthUpdate",
                "E": 1_700_000_000_000,
                "T": 1_700_000_000_000,
                "s": symbol,
                "U": first_update_id if first_update_id is not None else final_update_id - 1,
                "u": final_update_id,
                "pu": previous_final_update_id,
                "b": [["100", "1"]],
                "a": [],
            },
        },
        separators=(",", ":"),
    )


def _trade_message(trade_id: int, *, symbol: str = "BTCUSDT") -> str:
    return json.dumps(
        {
            "stream": f"{symbol.lower()}@trade",
            "data": {
                "e": "trade",
                "E": 1_700_000_000_000,
                "T": 1_700_000_000_000,
                "s": symbol,
                "t": trade_id,
                "p": "100",
                "q": "1",
                "X": "MARKET",
                "m": True,
            },
        },
        separators=(",", ":"),
    )


def _collector(
    symbols, tmp_path: Path, snapshot_ids: dict[str, int], **kwargs
) -> RawBinanceCollector:
    return RawBinanceCollector(
        symbols, tmp_path, depth_snapshot_fetcher=_fake_fetcher(snapshot_ids), **kwargs
    )


def test_subscribe_streams_cover_every_channel_for_every_symbol(tmp_path: Path) -> None:
    collector = _collector(("BTCUSDT", "ETHUSDT"), tmp_path, {"BTCUSDT": 1, "ETHUSDT": 1})

    assert collector.subscribe_streams == (
        "btcusdt@trade",
        "btcusdt@depth@100ms",
        "btcusdt@markPrice@1s",
        "btcusdt@forceOrder",
        "ethusdt@trade",
        "ethusdt@depth@100ms",
        "ethusdt@markPrice@1s",
        "ethusdt@forceOrder",
    )


def test_collector_id_is_safe_for_health_file_paths(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="collector_id"):
        _collector(("BTCUSDT",), tmp_path, {"BTCUSDT": 1}, collector_id="../escape")


def test_open_subscribes_all_streams_bootstraps_gates_and_publishes_health(
    tmp_path: Path,
) -> None:
    collector = _collector(("BTCUSDT",), tmp_path, {"BTCUSDT": 500})
    collector._prepare_connection()
    ws = FakeWS()

    collector._on_open(ws)
    request = json.loads(ws.sent[0])

    assert request["method"] == "SUBSCRIBE"
    assert request["params"] == list(collector.subscribe_streams)
    assert collector._books["BTCUSDT"].update_id == 500
    assert collector._books["BTCUSDT"].connection_id == collector._connection_id
    assert (tmp_path / "health" / "binance-linear-all.json").is_file()


def test_snapshot_fetch_failure_leaves_gate_unbootstrapped_but_still_opens(
    tmp_path: Path,
) -> None:
    collector = RawBinanceCollector(
        ("BTCUSDT",), tmp_path, depth_snapshot_fetcher=_failing_fetcher
    )
    collector._prepare_connection()
    ws = FakeWS()

    collector._on_open(ws)

    assert collector._books["BTCUSDT"].update_id is None
    assert "snapshot fetch failed" in (collector.health.snapshot()["last_error"] or "")
    # subscription still went out - a snapshot failure is not fatal to the
    # connection, just to that symbol's continuity guarantee until retried
    assert len(ws.sent) == 1


def test_valid_depth_sequence_after_bootstrap_does_not_flag_uncertainty(
    tmp_path: Path,
) -> None:
    collector = _collector(("BTCUSDT",), tmp_path, {"BTCUSDT": 100})
    collector._prepare_connection()
    ws = FakeWS()
    collector._active_ws = ws
    collector._bootstrap_depth_gates()

    collector.handle_raw_message(_depth_message(150, 100, first_update_id=50))  # bridges
    collector.handle_raw_message(_depth_message(200, 150))
    collector.handle_raw_message(_trade_message(1))

    snapshot = collector.health.snapshot(queue_depth=collector._queue.qsize())
    assert collector._queue.qsize() == 3
    assert snapshot["sequence_uncertainty_count"] == 0
    assert ws.close_count == 0


def test_stale_pre_snapshot_depth_events_are_silently_skipped_not_flagged(
    tmp_path: Path,
) -> None:
    """Binance's official procedure: events at or before the snapshot's
    lastUpdateId are simply dropped, not treated as an error."""
    collector = _collector(("BTCUSDT",), tmp_path, {"BTCUSDT": 500})
    collector._prepare_connection()
    ws = FakeWS()
    collector._active_ws = ws
    collector._bootstrap_depth_gates()

    collector.handle_raw_message(_depth_message(300, 250))  # stale: u <= 500

    snapshot = collector.health.snapshot(queue_depth=collector._queue.qsize())
    assert collector._queue.qsize() == 1  # still raw-captured
    assert snapshot["sequence_uncertainty_count"] == 0
    assert ws.close_count == 0


def test_depth_event_before_bootstrap_completes_is_fail_closed(tmp_path: Path) -> None:
    collector = _collector(("BTCUSDT",), tmp_path, {"BTCUSDT": 100})
    collector._prepare_connection()
    ws = FakeWS()
    collector._active_ws = ws
    # no _bootstrap_depth_gates() call - simulates a gate that never got a
    # snapshot (e.g. fetch failure)

    collector.handle_raw_message(_depth_message(150, 100))

    snapshot = collector.health.snapshot(queue_depth=collector._queue.qsize())
    assert collector._queue.qsize() == 1  # raw capture unaffected
    assert snapshot["sequence_uncertainty_count"] == 1
    assert ws.close_count == 1


def test_sequence_gap_after_bootstrap_is_raw_queued_then_connection_is_closed(
    tmp_path: Path,
) -> None:
    collector = _collector(("BTCUSDT",), tmp_path, {"BTCUSDT": 100})
    collector._prepare_connection()
    ws = FakeWS()
    collector._active_ws = ws
    collector._bootstrap_depth_gates()
    collector.handle_raw_message(
        _depth_message(150, 100, first_update_id=50)
    )  # bridges the snapshot

    collector.handle_raw_message(_depth_message(300, 250))  # gap: expected pu=150

    snapshot = collector.health.snapshot(queue_depth=collector._queue.qsize())
    assert collector._queue.qsize() == 2  # raw capture unaffected
    assert snapshot["sequence_uncertainty_count"] == 1
    assert snapshot["dropped_event_count"] == 0
    assert ws.close_count == 1


def test_sequence_uncertain_state_is_not_rechecked_until_next_connection(
    tmp_path: Path,
) -> None:
    collector = _collector(("BTCUSDT",), tmp_path, {"BTCUSDT": 100})
    collector._prepare_connection()
    ws = FakeWS()
    collector._active_ws = ws
    collector._bootstrap_depth_gates()
    collector.handle_raw_message(_depth_message(150, 100, first_update_id=50))
    collector.handle_raw_message(_depth_message(300, 250))  # triggers uncertainty
    assert collector._sequence_uncertain is True

    collector.handle_raw_message(_depth_message(999, 998))  # would also "gap"

    snapshot = collector.health.snapshot(queue_depth=collector._queue.qsize())
    assert collector._queue.qsize() == 3
    assert snapshot["sequence_uncertainty_count"] == 1  # not incremented again


def test_prepare_connection_resets_depth_gates_for_a_fresh_connection(tmp_path: Path) -> None:
    collector = _collector(("BTCUSDT",), tmp_path, {"BTCUSDT": 100})
    collector._prepare_connection()
    ws = FakeWS()
    collector._active_ws = ws
    collector._bootstrap_depth_gates()
    collector.handle_raw_message(_depth_message(150, 100, first_update_id=50))
    collector.handle_raw_message(_depth_message(300, 250))  # triggers uncertainty
    assert collector._sequence_uncertain is True

    collector._prepare_connection()  # simulates run_forever()'s reconnect loop

    assert collector._sequence_uncertain is False
    assert collector._books["BTCUSDT"].update_id is None  # fresh, unbootstrapped gate
    new_ws = FakeWS()
    collector._active_ws = new_ws
    collector._bootstrap_depth_gates()
    collector.handle_raw_message(_depth_message(5, -1))
    assert collector.health.snapshot()["sequence_uncertainty_count"] == 1  # unchanged
    assert new_ws.close_count == 0


def test_other_symbols_are_unaffected_by_one_symbols_gap(tmp_path: Path) -> None:
    """Depth continuity is per-symbol - a BTC gap must not affect ETH."""
    collector = _collector(("BTCUSDT", "ETHUSDT"), tmp_path, {"BTCUSDT": 100, "ETHUSDT": 40})
    collector._prepare_connection()
    ws = FakeWS()
    collector._active_ws = ws
    collector._bootstrap_depth_gates()

    collector.handle_raw_message(
        _depth_message(150, 100, first_update_id=50, symbol="BTCUSDT")
    )  # bridges
    collector.handle_raw_message(_depth_message(300, 250, symbol="BTCUSDT"))  # BTC gap
    collector.handle_raw_message(
        _depth_message(50, 40, first_update_id=20, symbol="ETHUSDT")
    )  # bridges
    collector.handle_raw_message(_depth_message(60, 50, symbol="ETHUSDT"))

    # the shared connection-level flag means one symbol's gap does stop
    # further gate checks on this connection (fail-closed forces a full
    # reconnect rather than per-symbol suppression) - but raw capture for
    # every symbol is unaffected
    assert collector._queue.qsize() == 4
    assert ws.close_count == 1


def test_queue_overflow_stops_instead_of_silently_dropping(tmp_path: Path) -> None:
    collector = _collector(("BTCUSDT",), tmp_path, {"BTCUSDT": 1}, queue_capacity=1)
    collector._prepare_connection()

    collector.handle_raw_message(_depth_message(1, -1))
    collector.handle_raw_message(_depth_message(2, -1))

    snapshot = collector.health.snapshot()
    assert snapshot["dropped_event_count"] == 1
    assert snapshot["status"] == "failed"
    assert collector._shutdown.is_set()


def test_storage_reserve_breach_stops_before_subscribing(tmp_path: Path) -> None:
    gib = 1024**3
    collector = _collector(
        ("BTCUSDT",),
        tmp_path,
        {"BTCUSDT": 1},
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
    collector = _collector(
        ("BTCUSDT",), tmp_path, {"BTCUSDT": 1}, flush_interval_secs=60, health_interval_secs=60
    )
    collector._prepare_connection()
    collector._start_background_workers()
    payload = _depth_message(1, -1)
    collector.handle_raw_message(payload)

    collector.stop()

    events = load_raw_events(tmp_path, channel="orderbook", symbol="BTCUSDT")
    assert len(events) == 1
    assert events[0].payload_text == payload
    health = collector.health.snapshot()
    assert health["events_written"] == 1
    assert health["status"] == "stopped"


def test_non_utf8_message_fails_closed(tmp_path: Path) -> None:
    collector = _collector(("BTCUSDT",), tmp_path, {"BTCUSDT": 1})
    collector._prepare_connection()

    collector.handle_raw_message(b"\xff")

    assert collector.health.snapshot()["dropped_event_count"] == 1
    assert collector._shutdown.is_set()


def test_ping_interval_and_timeout_are_validated(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="ping timeout"):
        _collector(
            ("BTCUSDT",), tmp_path, {"BTCUSDT": 1}, ping_interval_secs=10, ping_timeout_secs=10
        )


def test_health_reports_sequence_continuity_as_verified(tmp_path: Path) -> None:
    collector = _collector(("BTCUSDT",), tmp_path, {"BTCUSDT": 1})
    assert collector.health.snapshot()["sequence_continuity_verified"] is True


def test_default_depth_snapshot_fetcher_is_used_when_none_injected(tmp_path: Path) -> None:
    from src.data.binance_raw_collector import default_depth_snapshot_fetcher

    collector = RawBinanceCollector(("BTCUSDT",), tmp_path)
    assert collector._depth_snapshot_fetcher is default_depth_snapshot_fetcher
