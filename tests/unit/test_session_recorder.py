from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

from src.execution.intent import IntentSide, OrderIntent
from src.execution.session_recorder import SessionRecorder


@dataclass
class _FakeFilled:
    client_order_id: str
    last_px: float
    last_qty: float
    ts_event: int


@dataclass
class _FakeRejected:
    client_order_id: str
    reason: str
    ts_event: int


def _intent() -> OrderIntent:
    return OrderIntent(
        symbol="BTCUSDT",
        side=IntentSide.BUY,
        quantity=1.0,
        reference_price=100.0,
        created_at=datetime(2024, 1, 1, tzinfo=UTC),
        reason="test",
    )


class TestSessionRecorderFilled:
    def test_records_a_matching_fill(self) -> None:
        recorder = SessionRecorder()
        recorder.record_intent("O-1", _intent())
        recorder.on_order_filled(
            _FakeFilled(
                client_order_id="O-1",
                last_px=101.0,
                last_qty=1.0,
                ts_event=1_700_000_000_000_000_000,
            )
        )
        summary = recorder.summary()
        assert summary.n_intents == 1
        assert summary.n_rejected == 0

    def test_unrecorded_client_order_id_is_silently_dropped(self) -> None:
        recorder = SessionRecorder()
        recorder.on_order_filled(
            _FakeFilled(client_order_id="unknown", last_px=101.0, last_qty=1.0, ts_event=1)
        )
        assert recorder.summary().n_intents == 0

    def test_pending_intent_is_consumed_once(self) -> None:
        recorder = SessionRecorder()
        recorder.record_intent("O-1", _intent())
        recorder.on_order_filled(
            _FakeFilled(client_order_id="O-1", last_px=101.0, last_qty=1.0, ts_event=1)
        )
        recorder.on_order_filled(
            _FakeFilled(client_order_id="O-1", last_px=102.0, last_qty=1.0, ts_event=2)
        )
        assert recorder.summary().n_intents == 1


class TestSessionRecorderRejected:
    def test_records_a_rejection(self) -> None:
        recorder = SessionRecorder()
        recorder.record_intent("O-1", _intent())
        recorder.on_order_rejected(
            _FakeRejected(client_order_id="O-1", reason="no funds", ts_event=1)
        )
        summary = recorder.summary()
        assert summary.n_intents == 1
        assert summary.n_rejected == 1
