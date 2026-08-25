from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import pytest

from src.engines.contracts import SetupAction
from src.execution.demo_autonomous_risk import AutonomousDemoRiskConfig
from src.execution.demo_autonomous_state import (
    AutonomousDemoEntryNotAuthorizedError,
    AutonomousDemoStateError,
    AutonomousDemoStateStore,
    AutonomousTradePhase,
)


def _begin(store: AutonomousDemoStateStore, now: datetime, suffix: str = "1"):
    return store.begin_trade(
        observation_id=f"observation-{suffix}",
        candidate_id="candidate-v1",
        symbol="BTCUSDT",
        action=SetupAction.LONG,
        target_quantity=Decimal("0.123"),
        reference_price=Decimal("80000"),
        now_utc=now,
    )


def test_trade_lifecycle_survives_restart_and_replays_idempotently(tmp_path: Path) -> None:
    path = tmp_path / "autonomous.sqlite3"
    now = datetime(2026, 8, 24, 12, tzinfo=UTC)
    store = AutonomousDemoStateStore(path)
    observed = _begin(store, now)
    assert observed == _begin(AutonomousDemoStateStore(path), now)

    submitted = store.mark_entry_submitted(
        observed.trade_id, client_order_id="paper-entry", now_utc=now
    )
    assert submitted.phase is AutonomousTradePhase.ENTRY_SUBMITTED
    assert (
        store.mark_entry_submitted(observed.trade_id, client_order_id="paper-entry", now_utc=now)
        == submitted
    )
    opened = store.mark_open(
        observed.trade_id,
        fill_price=Decimal("79990"),
        opened_at_utc=now + timedelta(seconds=1),
    )
    assert opened.phase is AutonomousTradePhase.OPEN
    exiting = store.mark_exit_submitted(
        observed.trade_id,
        client_order_id="paper-exit",
        reason="TAKE_PROFIT",
        now_utc=now + timedelta(minutes=1),
    )
    assert exiting.phase is AutonomousTradePhase.EXIT_SUBMITTED
    closed = store.mark_closed(
        observed.trade_id,
        realized_pnl_usd=Decimal("3.25"),
        closed_at_utc=now + timedelta(minutes=2),
    )
    assert closed.phase is AutonomousTradePhase.CLOSED
    assert closed.realized_pnl_usd == Decimal("3.25")
    assert AutonomousDemoStateStore(path).active_trade() is None


def test_only_one_active_trade_is_permitted(tmp_path: Path) -> None:
    now = datetime(2026, 8, 24, 12, tzinfo=UTC)
    store = AutonomousDemoStateStore(tmp_path / "state.sqlite3")
    _begin(store, now)

    with pytest.raises(AutonomousDemoStateError, match="another"):
        _begin(store, now, "2")


def test_reused_observation_with_different_payload_fails(tmp_path: Path) -> None:
    now = datetime(2026, 8, 24, 12, tzinfo=UTC)
    store = AutonomousDemoStateStore(tmp_path / "state.sqlite3")
    _begin(store, now)

    with pytest.raises(AutonomousDemoStateError, match="conflicts"):
        store.begin_trade(
            observation_id="observation-1",
            candidate_id="candidate-v1",
            symbol="ETHUSDT",
            action=SetupAction.LONG,
            target_quantity=Decimal("0.123"),
            reference_price=Decimal("80000"),
            now_utc=now,
        )


def test_illegal_close_without_entry_fails(tmp_path: Path) -> None:
    now = datetime(2026, 8, 24, 12, tzinfo=UTC)
    store = AutonomousDemoStateStore(tmp_path / "state.sqlite3")
    trade = _begin(store, now)

    with pytest.raises(AutonomousDemoStateError, match="cannot move"):
        store.mark_closed(
            trade.trade_id,
            realized_pnl_usd=Decimal("0"),
            closed_at_utc=now,
        )


def test_unsubmitted_safety_hold_can_be_closed_after_flat_account_proof(
    tmp_path: Path,
) -> None:
    now = datetime(2026, 8, 24, 12, tzinfo=UTC)
    store = AutonomousDemoStateStore(tmp_path / "state.sqlite3")
    trade = _begin(store, now)
    store.mark_safety_hold(trade.trade_id, reason="pre-submit failure", now_utc=now)

    closed = store.close_unsubmitted_safety_hold(
        trade.trade_id, closed_at_utc=now + timedelta(seconds=1)
    )
    assert closed.phase is AutonomousTradePhase.CLOSED
    assert closed.realized_pnl_usd == 0
    assert closed.exit_reason == "UNSUBMITTED_ATTEMPT_CLEARED"
    assert store.active_trade() is None


def test_safety_hold_with_order_identity_cannot_be_cleared(tmp_path: Path) -> None:
    now = datetime(2026, 8, 24, 12, tzinfo=UTC)
    store = AutonomousDemoStateStore(tmp_path / "state.sqlite3")
    trade = _begin(store, now)
    store.mark_entry_submitted(trade.trade_id, client_order_id="paper-entry", now_utc=now)
    store.mark_safety_hold(trade.trade_id, reason="ambiguous", now_utc=now)

    with pytest.raises(AutonomousDemoStateError, match="order exposure"):
        store.close_unsubmitted_safety_hold(trade.trade_id, closed_at_utc=now)


def test_daily_cooldown_and_trade_limit_are_enforced_atomically(tmp_path: Path) -> None:
    now = datetime(2026, 8, 24, 12, tzinfo=UTC)
    store = AutonomousDemoStateStore(tmp_path / "state.sqlite3")
    capital = Decimal("100")
    config = AutonomousDemoRiskConfig(maximum_trades_per_utc_day=1)

    assert (
        store.authorize_entry(now_utc=now, starting_capital_usd=capital, config=config).entries == 0
    )
    assert store.record_entry(now_utc=now, starting_capital_usd=capital, config=config).entries == 1
    store.record_close(
        now_utc=now,
        starting_capital_usd=capital,
        realized_pnl_usd=Decimal("0.1"),
        config=config,
    )
    with pytest.raises(AutonomousDemoEntryNotAuthorizedError, match="trade limit"):
        store.record_entry(
            now_utc=now + timedelta(hours=1),
            starting_capital_usd=capital,
            config=config,
        )


def test_cooldown_rejection_is_the_retryable_not_authorized_subclass(tmp_path: Path) -> None:
    """A caller (e.g. the scalper run loop) needs to tell "not yet allowed,
    retry later" apart from a corrupted/ambiguous durable state - this is
    what it must catch to do that safely."""
    now = datetime(2026, 8, 24, 12, tzinfo=UTC)
    store = AutonomousDemoStateStore(tmp_path / "state.sqlite3")
    capital = Decimal("100")
    store.authorize_entry(now_utc=now, starting_capital_usd=capital)
    store.record_entry(now_utc=now, starting_capital_usd=capital)
    store.record_close(now_utc=now, starting_capital_usd=capital, realized_pnl_usd=Decimal("0.1"))

    with pytest.raises(AutonomousDemoEntryNotAuthorizedError, match="cooldown"):
        store.authorize_entry(
            now_utc=now + timedelta(seconds=1), starting_capital_usd=capital
        )


def test_daily_loss_activates_durable_kill_switch(tmp_path: Path) -> None:
    now = datetime(2026, 8, 24, 12, tzinfo=UTC)
    path = tmp_path / "state.sqlite3"
    store = AutonomousDemoStateStore(path)
    result = store.record_close(
        now_utc=now,
        starting_capital_usd=Decimal("100"),
        realized_pnl_usd=Decimal("-1"),
    )
    assert result.kill_switch_reason == "DAILY_LOSS_LIMIT"

    with pytest.raises(AutonomousDemoEntryNotAuthorizedError, match="kill switch"):
        AutonomousDemoStateStore(path).authorize_entry(
            now_utc=now + timedelta(hours=1),
            starting_capital_usd=Decimal("100"),
        )


def test_starting_capital_cannot_change_inside_utc_day(tmp_path: Path) -> None:
    now = datetime(2026, 8, 24, 12, tzinfo=UTC)
    store = AutonomousDemoStateStore(tmp_path / "state.sqlite3")
    store.authorize_entry(now_utc=now, starting_capital_usd=Decimal("100"))

    with pytest.raises(AutonomousDemoStateError, match="changed"):
        store.authorize_entry(
            now_utc=now + timedelta(minutes=1),
            starting_capital_usd=Decimal("101"),
        )
