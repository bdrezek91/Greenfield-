from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest

from src.execution.demo_signal_journal import DemoSignalJournalEntry
from src.execution.demo_signal_validation import (
    validate_demo_signals,
    write_demo_signal_validation_report,
)


def _entry(index: int, *, action: str = "WAIT", forced: bool = False):
    return DemoSignalJournalEntry(
        observation_id=f"observation-{index}",
        observed_at_utc=datetime(2026, 8, 25, tzinfo=UTC) + timedelta(seconds=index * 60),
        symbol="BTCUSDT",
        market_price=100.0 + index,
        experimental_action=action,
        directional_action="WAIT",
        momentum_veto="LONG",
        evidence_json=(
            '[{"family":"price_auction"},{"family":"order_flow"},'
            '{"family":"derivatives"}]'
        ),
        reason_codes_json="[]",
        execution_status="WAIT",
        execution_detail="test",
        trade_id=None,
        operator_forced=forced,
    )


def test_validation_labels_only_matured_future_observations() -> None:
    entries = tuple(_entry(index, action="LONG" if index == 0 else "WAIT") for index in range(4))
    report = validate_demo_signals(
        entries, horizons_seconds=(60, 120), minimum_observations=1
    )

    assert report.qualified
    assert report.family_observation_counts == {
        "derivatives": 4,
        "order_flow": 4,
        "price_auction": 4,
    }
    assert report.horizons[0].labeled_observation_count == 3
    assert report.horizons[0].actionable_count == 1
    assert report.horizons[0].profitable_action_count == 1
    assert report.horizons[1].labeled_observation_count == 2


def test_validation_excludes_operator_forced_and_stays_unqualified_without_actions() -> None:
    entries = (_entry(0, forced=True), _entry(1), _entry(2))
    report = validate_demo_signals(entries, horizons_seconds=(60,), minimum_observations=2)

    assert not report.qualified
    assert report.eligible_observation_count == 2
    assert report.reasons == ("INSUFFICIENT_MATURED_OUTCOMES", "NO_ACTIONABLE_SIGNALS")


def test_validation_rejects_bad_configuration_and_report_overwrite(tmp_path) -> None:
    with pytest.raises(ValueError, match="configuration"):
        validate_demo_signals((_entry(0),), horizons_seconds=(0,))
    report = validate_demo_signals(
        tuple(replace(_entry(index), experimental_action="LONG") for index in range(3)),
        horizons_seconds=(60,),
        minimum_observations=1,
    )
    path = tmp_path / "report.json"
    write_demo_signal_validation_report(path, report)
    with pytest.raises(FileExistsError, match="will not be overwritten"):
        write_demo_signal_validation_report(path, report)
