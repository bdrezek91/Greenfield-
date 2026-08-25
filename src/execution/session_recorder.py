"""Bridges a live/paper NautilusTrader strategy's real OrderFilled/
OrderRejected events into src.execution.fill_tracking.FillTracker.

Phase 10 built FillTracker and proved the section-32 comparison pipeline
end to end using replayed backtest trades
(src.execution.backtest_bridge.trades_to_intents +
tests/integration/test_paper_dry_run.py), but never actually wired it to a
live-running strategy - there was no path from "an order was submitted"
to "here is the intent that fill should be compared against". This module
is that path: src.strategies.base.HoldForBarsStrategy calls
`record_intent()` right before `submit_order()` (see base.py), then
forwards its `on_order_filled`/`on_order_rejected` callbacks here.

Not NautilusTrader-specific by need - only `on_order_filled`/
`on_order_rejected` receive NautilusTrader Event objects (from
`nautilus_trader.model.events`), so this doesn't require importing
NautilusTrader's Strategy base itself.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Protocol

from src.execution.adapter import Fill
from src.execution.fill_tracking import FillTracker, FillTrackerSummary
from src.execution.intent import OrderIntent


class _OrderFilledEvent(Protocol):
    client_order_id: object
    last_px: object
    last_qty: object
    ts_event: int


class _OrderRejectedEvent(Protocol):
    client_order_id: object
    reason: object
    ts_event: int


def _ns_to_datetime(ts_event: int) -> datetime:
    return datetime.fromtimestamp(ts_event / 1_000_000_000, tz=UTC)


class SessionRecorder:
    """One instance per strategy/session. `record_intent` must be called
    with the SAME `client_order_id` NautilusTrader assigned to the order
    at submission time, before `submit_order()` is called - otherwise the
    matching `on_order_filled`/`on_order_rejected` event has nothing to
    compare against and is silently dropped (a fill without a recorded
    intent isn't a bug to raise on; it just can't be scored - e.g. orders
    placed outside this recorder's strategy, or a recorder attached mid-flight).
    """

    def __init__(self, tracker: FillTracker | None = None) -> None:
        self.tracker = tracker or FillTracker()
        self._pending: dict[object, OrderIntent] = {}
        self._filled_quantity: dict[object, float] = {}
        self._seen_fills: set[tuple[object, int, str, str]] = set()

    def record_intent(self, client_order_id: object, intent: OrderIntent) -> None:
        self._pending[client_order_id] = intent
        self._filled_quantity[client_order_id] = 0.0

    def on_order_filled(self, event: _OrderFilledEvent) -> None:
        intent = self._pending.get(event.client_order_id)
        if intent is None:
            return
        identity = (
            event.client_order_id,
            event.ts_event,
            str(event.last_px),
            str(event.last_qty),
        )
        if identity in self._seen_fills:
            return
        self._seen_fills.add(identity)
        quantity = float(event.last_qty)  # type: ignore[arg-type]
        fill = Fill(
            intent=intent,
            filled_price=float(event.last_px),  # type: ignore[arg-type]
            filled_quantity=quantity,
            filled_at=_ns_to_datetime(event.ts_event),
        )
        self.tracker.record(intent, fill)
        cumulative = self._filled_quantity.get(event.client_order_id, 0.0) + quantity
        self._filled_quantity[event.client_order_id] = cumulative
        if cumulative >= intent.quantity - 1e-9:
            self._pending.pop(event.client_order_id, None)
            self._filled_quantity.pop(event.client_order_id, None)

    def on_order_rejected(self, event: _OrderRejectedEvent) -> None:
        intent = self._pending.pop(event.client_order_id, None)
        if intent is None:
            return
        self._filled_quantity.pop(event.client_order_id, None)
        fill = Fill(
            intent=intent,
            filled_price=0.0,
            filled_quantity=0.0,
            filled_at=_ns_to_datetime(event.ts_event),
            rejected=True,
            reject_reason=str(event.reason),
        )
        self.tracker.record(intent, fill)

    def summary(self) -> FillTrackerSummary:
        return self.tracker.summary()
