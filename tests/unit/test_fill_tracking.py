"""compare_fill/FillTracker must correctly measure latency, slippage
direction, rejections, and data issues - the project brief section 32
checklist.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from src.execution.adapter import Fill
from src.execution.fill_tracking import FillTracker, compare_fill
from src.execution.intent import IntentSide, OrderIntent


def _intent(side: IntentSide = IntentSide.BUY, reference_price: float = 100.0) -> OrderIntent:
    return OrderIntent(
        symbol="BTCUSD",
        side=side,
        quantity=1.0,
        reference_price=reference_price,
        created_at=datetime(2024, 1, 1, 12, 0, 0, tzinfo=UTC),
    )


def test_buy_worse_fill_price_is_positive_slippage() -> None:
    intent = _intent(side=IntentSide.BUY, reference_price=100.0)
    fill = Fill(
        intent=intent,
        filled_price=100.5,  # paid more than expected -> bad for a buyer
        filled_quantity=1.0,
        filled_at=intent.created_at + timedelta(seconds=1),
    )
    comparison = compare_fill(intent, fill)
    assert comparison.slippage == pytest.approx(0.5)
    assert comparison.slippage_pct == pytest.approx(0.005)


def test_sell_worse_fill_price_is_positive_slippage() -> None:
    intent = _intent(side=IntentSide.SELL, reference_price=100.0)
    fill = Fill(
        intent=intent,
        filled_price=99.5,  # received less than expected -> bad for a seller
        filled_quantity=1.0,
        filled_at=intent.created_at + timedelta(seconds=1),
    )
    comparison = compare_fill(intent, fill)
    assert comparison.slippage == pytest.approx(0.5)


def test_buy_better_fill_price_is_negative_slippage() -> None:
    intent = _intent(side=IntentSide.BUY, reference_price=100.0)
    fill = Fill(
        intent=intent,
        filled_price=99.8,  # paid less than expected -> good
        filled_quantity=1.0,
        filled_at=intent.created_at + timedelta(seconds=1),
    )
    comparison = compare_fill(intent, fill)
    assert comparison.slippage == pytest.approx(-0.2)


def test_latency_measured_correctly() -> None:
    intent = _intent()
    fill = Fill(
        intent=intent,
        filled_price=100.0,
        filled_quantity=1.0,
        filled_at=intent.created_at + timedelta(milliseconds=250),
    )
    comparison = compare_fill(intent, fill)
    assert comparison.latency_seconds == pytest.approx(0.25)


def test_rejected_fill_has_no_slippage_or_latency() -> None:
    intent = _intent()
    fill = Fill(
        intent=intent,
        filled_price=0.0,
        filled_quantity=0.0,
        filled_at=intent.created_at,
        rejected=True,
        reject_reason="insufficient margin",
    )
    comparison = compare_fill(intent, fill)
    assert comparison.rejected
    assert comparison.slippage is None
    assert comparison.latency_seconds is None
    assert comparison.data_issue is None


def test_data_issue_negative_latency() -> None:
    intent = _intent()
    fill = Fill(
        intent=intent,
        filled_price=100.0,
        filled_quantity=1.0,
        filled_at=intent.created_at - timedelta(seconds=1),  # before the intent - bad data
    )
    comparison = compare_fill(intent, fill)
    assert comparison.data_issue == "filled_at is before created_at"


def test_data_issue_zero_quantity() -> None:
    intent = _intent()
    fill = Fill(
        intent=intent, filled_price=100.0, filled_quantity=0.0, filled_at=intent.created_at
    )
    comparison = compare_fill(intent, fill)
    assert comparison.data_issue == "zero or negative filled quantity"


def test_data_issue_partial_fill() -> None:
    intent = _intent()
    fill = Fill(
        intent=intent, filled_price=100.0, filled_quantity=0.5, filled_at=intent.created_at
    )
    comparison = compare_fill(intent, fill)
    assert comparison.data_issue == "partial fill (filled_quantity != requested quantity)"


def test_clean_fill_has_no_data_issue() -> None:
    intent = _intent()
    fill = Fill(
        intent=intent, filled_price=100.1, filled_quantity=1.0, filled_at=intent.created_at
    )
    comparison = compare_fill(intent, fill)
    assert comparison.data_issue is None


def test_fill_tracker_summary_aggregates_correctly() -> None:
    tracker = FillTracker()

    intent1 = _intent(reference_price=100.0)
    tracker.record(
        intent1,
        Fill(
            intent=intent1,
            filled_price=100.5,
            filled_quantity=1.0,
            filled_at=intent1.created_at + timedelta(seconds=1),
        ),
    )

    intent2 = _intent(reference_price=100.0)
    tracker.record(
        intent2,
        Fill(
            intent=intent2,
            filled_price=100.0,
            filled_quantity=1.0,
            filled_at=intent2.created_at + timedelta(seconds=3),
        ),
    )

    intent3 = _intent(reference_price=100.0)
    tracker.record(
        intent3,
        Fill(
            intent=intent3,
            filled_price=0.0,
            filled_quantity=0.0,
            filled_at=intent3.created_at,
            rejected=True,
            reject_reason="no margin",
        ),
    )

    summary = tracker.summary()
    assert summary.n_intents == 3
    assert summary.n_rejected == 1
    assert summary.rejection_rate == pytest.approx(1 / 3)
    assert summary.mean_latency_seconds == pytest.approx(2.0)  # (1+3)/2
    assert summary.mean_slippage == pytest.approx(0.25)  # (0.5+0)/2


def test_fill_tracker_summary_empty() -> None:
    tracker = FillTracker()
    summary = tracker.summary()
    assert summary.n_intents == 0
    assert summary.rejection_rate != summary.rejection_rate  # nan
    assert summary.mean_latency_seconds is None


def test_fill_tracker_collects_data_issues() -> None:
    tracker = FillTracker()
    intent = _intent()
    tracker.record(
        intent,
        Fill(intent=intent, filled_price=100.0, filled_quantity=0.5, filled_at=intent.created_at),
    )
    summary = tracker.summary()
    assert summary.data_issue_count == 1
    assert "partial fill" in summary.data_issues[0]
