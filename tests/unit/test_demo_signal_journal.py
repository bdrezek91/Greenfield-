from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime

import pytest

from src.execution.demo_signal_journal import (
    DemoSignalJournal,
    DemoSignalJournalEntry,
    DemoSignalJournalError,
)


def _entry(*, detail: str = "families not aligned") -> DemoSignalJournalEntry:
    return DemoSignalJournalEntry(
        observation_id="BTCUSDT:2026-08-25T17:00:00+00:00",
        observed_at_utc=datetime(2026, 8, 25, 17, tzinfo=UTC),
        symbol="BTCUSDT",
        market_price=110_000.25,
        experimental_action="WAIT",
        directional_action="WAIT",
        momentum_veto="LONG",
        evidence_json='[{"family":"order_flow"}]',
        reason_codes_json='["PROMOTION_STATE_NOT_ELIGIBLE"]',
        execution_status="WAIT",
        execution_detail=detail,
        trade_id=None,
        operator_forced=False,
    )


def test_journal_is_durable_and_identical_replay_is_idempotent(tmp_path) -> None:
    path = tmp_path / "signals.sqlite3"
    journal = DemoSignalJournal(path)

    journal.record(_entry())
    journal.record(_entry())

    assert DemoSignalJournal(path).entries() == (_entry(),)


def test_journal_rejects_conflicting_observation_replay(tmp_path) -> None:
    journal = DemoSignalJournal(tmp_path / "signals.sqlite3")
    journal.record(_entry())

    with pytest.raises(DemoSignalJournalError, match="conflicts"):
        journal.record(_entry(detail="different result"))


def test_journal_rejects_naive_timestamp_and_invalid_price() -> None:
    with pytest.raises(ValueError, match="timezone-aware"):
        replace(_entry(), observed_at_utc=datetime(2026, 8, 25, 17))
    with pytest.raises(ValueError, match="positive and finite"):
        replace(_entry(), market_price=0)
