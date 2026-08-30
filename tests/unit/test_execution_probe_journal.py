from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from src.execution.calibration import (
    JoinIssue,
    PaperOrderObservation,
    TopOfBookQuote,
    compute_markout_calibration,
    join_orders_to_prior_quotes,
)
from src.execution.execution_probe_journal import ExecutionProbeJournal
from src.execution.intent import IntentSide

NOW = datetime(2026, 8, 27, 12, 0, tzinfo=UTC)


def _quote(offset_seconds: float, *, bid: float, ask: float, seq: int) -> TopOfBookQuote:
    return TopOfBookQuote(
        symbol="BTCUSDT",
        venue="bybit-demo",
        timestamp_utc=NOW + timedelta(seconds=offset_seconds),
        source_sequence=seq,
        bid_price=bid,
        ask_price=ask,
        bid_quantity=10.0,
        ask_quantity=10.0,
    )


def test_round_trips_an_observation_and_feeds_the_existing_calibration_join(tmp_path: Path) -> None:
    journal = ExecutionProbeJournal(tmp_path / "journal.sqlite3")
    reference = _quote(-1, bid=999.5, ask=1000.5, seq=1)
    journal.record_quote(probe_trade_id="trade-1", horizon_label="REFERENCE", quote=reference)
    horizon = _quote(1, bid=1001.0, ask=1002.0, seq=2)
    journal.record_quote(probe_trade_id="trade-1", horizon_label="T+1.0s", quote=horizon)

    observation = PaperOrderObservation(
        order_id="paper-1",
        symbol="BTCUSDT",
        venue="bybit-demo",
        side=IntentSide.BUY,
        requested_quantity=0.03,
        decision_timestamp_utc=NOW,
        submitted_at_utc=NOW,
        resolved_at_utc=NOW,
        filled_price=1000.5,
        filled_quantity=0.03,
        rejected=False,
        fee_cost_quote=0.02,
        funding_cost_quote=0.0,
    )
    journal.record_order_observation(
        probe_trade_id="trade-1",
        probe_mode="TAKER",
        request_id="req-1",
        observation=observation,
        now_utc=NOW,
    )

    loaded_orders = journal.load_observations()
    loaded_quotes = journal.load_quotes()
    assert loaded_orders == (observation,)
    assert set(loaded_quotes) == {reference, horizon}
    quote_records = journal.load_quote_records()
    assert {item.horizon_label for item in quote_records} == {"REFERENCE", "T+1.0s"}
    assert {item.probe_trade_id for item in quote_records} == {"trade-1"}

    joined = join_orders_to_prior_quotes(loaded_orders, loaded_quotes, maximum_quote_age_seconds=5)
    assert joined[0].issue is None
    assert joined[0].valid_for_cost_calibration is True

    markouts = compute_markout_calibration(joined, loaded_quotes, horizons_seconds=(1.0,))
    assert len(markouts) == 1
    assert markouts[0].symbol == "BTCUSDT"
    assert markouts[0].horizon(1.0).sample_count == 1


def test_recording_the_same_order_or_quote_twice_is_idempotent(tmp_path: Path) -> None:
    journal = ExecutionProbeJournal(tmp_path / "journal.sqlite3")
    quote = _quote(0, bid=999.5, ask=1000.5, seq=1)
    journal.record_quote(probe_trade_id="trade-1", horizon_label="REFERENCE", quote=quote)
    journal.record_quote(probe_trade_id="trade-1", horizon_label="REFERENCE", quote=quote)
    assert len(journal.load_quotes()) == 1

    observation = PaperOrderObservation(
        order_id="paper-1",
        symbol="BTCUSDT",
        venue="bybit-demo",
        side=IntentSide.SELL,
        requested_quantity=0.03,
        decision_timestamp_utc=NOW,
        submitted_at_utc=NOW,
        resolved_at_utc=NOW,
        filled_price=999.5,
        filled_quantity=0.03,
        rejected=False,
        fee_cost_quote=0.02,
        funding_cost_quote=0.0,
    )
    journal.record_order_observation(
        probe_trade_id="trade-1",
        probe_mode="MAKER",
        request_id="req-1",
        observation=observation,
        now_utc=NOW,
    )
    journal.record_order_observation(
        probe_trade_id="trade-1",
        probe_mode="MAKER",
        request_id="req-1",
        observation=observation,
        now_utc=NOW,
    )
    assert len(journal.load_observations()) == 1


def test_conflicting_order_or_quote_identity_fails_closed(tmp_path: Path) -> None:
    journal = ExecutionProbeJournal(tmp_path / "journal.sqlite3")
    quote = _quote(0, bid=999.5, ask=1000.5, seq=1)
    journal.record_quote(probe_trade_id="trade-1", horizon_label="REFERENCE", quote=quote)
    with pytest.raises(ValueError, match="quote identity conflict"):
        journal.record_quote(
            probe_trade_id="trade-1",
            horizon_label="REFERENCE",
            quote=_quote(0, bid=998.5, ask=1000.5, seq=1),
        )

    observation = PaperOrderObservation(
        order_id="paper-1",
        symbol="BTCUSDT",
        venue="bybit-demo",
        side=IntentSide.BUY,
        requested_quantity=0.03,
        decision_timestamp_utc=NOW,
        submitted_at_utc=NOW,
        resolved_at_utc=NOW,
        filled_price=1000.5,
        filled_quantity=0.03,
        rejected=False,
        fee_cost_quote=0.02,
        funding_cost_quote=0.0,
    )
    journal.record_order_observation(
        probe_trade_id="trade-1",
        probe_mode="TAKER",
        request_id="req-1",
        observation=observation,
        now_utc=NOW,
    )
    conflicting = PaperOrderObservation(
        order_id=observation.order_id,
        symbol=observation.symbol,
        venue=observation.venue,
        side=observation.side,
        requested_quantity=observation.requested_quantity,
        decision_timestamp_utc=observation.decision_timestamp_utc,
        submitted_at_utc=observation.submitted_at_utc,
        resolved_at_utc=observation.resolved_at_utc,
        filled_price=999.0,
        filled_quantity=observation.filled_quantity,
        rejected=observation.rejected,
        fee_cost_quote=observation.fee_cost_quote,
        funding_cost_quote=observation.funding_cost_quote,
    )
    with pytest.raises(ValueError, match="order_id conflict"):
        journal.record_order_observation(
            probe_trade_id="trade-1",
            probe_mode="TAKER",
            request_id="req-1",
            observation=conflicting,
            now_utc=NOW,
        )


def test_since_filter_excludes_older_rows(tmp_path: Path) -> None:
    journal = ExecutionProbeJournal(tmp_path / "journal.sqlite3")
    older = PaperOrderObservation(
        order_id="paper-old",
        symbol="BTCUSDT",
        venue="bybit-demo",
        side=IntentSide.BUY,
        requested_quantity=0.03,
        decision_timestamp_utc=NOW - timedelta(days=2),
        submitted_at_utc=NOW - timedelta(days=2),
        resolved_at_utc=NOW - timedelta(days=2),
        filled_price=1000.0,
        filled_quantity=0.03,
        rejected=False,
        fee_cost_quote=0.02,
        funding_cost_quote=0.0,
    )
    newer = PaperOrderObservation(
        order_id="paper-new",
        symbol="BTCUSDT",
        venue="bybit-demo",
        side=IntentSide.BUY,
        requested_quantity=0.03,
        decision_timestamp_utc=NOW,
        submitted_at_utc=NOW,
        resolved_at_utc=NOW,
        filled_price=1000.0,
        filled_quantity=0.03,
        rejected=False,
        fee_cost_quote=0.02,
        funding_cost_quote=0.0,
    )
    journal.record_order_observation(
        probe_trade_id="trade-old", probe_mode="TAKER", request_id="req-old",
        observation=older, now_utc=NOW,
    )
    journal.record_order_observation(
        probe_trade_id="trade-new", probe_mode="TAKER", request_id="req-new",
        observation=newer, now_utc=NOW,
    )
    recent = journal.load_observations(since_utc=NOW - timedelta(hours=1))
    assert recent == (newer,)
    records = journal.load_probe_records(since_utc=NOW - timedelta(hours=1))
    assert len(records) == 1
    assert records[0].probe_trade_id == "trade-new"
    assert records[0].probe_mode == "TAKER"
    assert records[0].request_id == "req-new"
    assert records[0].observation == newer


def test_join_issue_is_reported_when_no_prior_quote_exists(tmp_path: Path) -> None:
    """Sanity check that the journal's raw dataclasses satisfy the exact
    shapes `join_orders_to_prior_quotes` expects, including its
    MISSING_QUOTE fail-closed path."""
    journal = ExecutionProbeJournal(tmp_path / "journal.sqlite3")
    observation = PaperOrderObservation(
        order_id="paper-1",
        symbol="ETHUSDT",
        venue="bybit-demo",
        side=IntentSide.BUY,
        requested_quantity=1.0,
        decision_timestamp_utc=NOW,
        submitted_at_utc=NOW,
        resolved_at_utc=NOW,
        filled_price=2500.0,
        filled_quantity=1.0,
        rejected=False,
        fee_cost_quote=0.5,
        funding_cost_quote=0.0,
    )
    journal.record_order_observation(
        probe_trade_id="trade-2", probe_mode="TAKER", request_id="req-2",
        observation=observation, now_utc=NOW,
    )
    joined = join_orders_to_prior_quotes(
        journal.load_observations(), journal.load_quotes(), maximum_quote_age_seconds=5
    )
    assert joined[0].issue is JoinIssue.MISSING_QUOTE
