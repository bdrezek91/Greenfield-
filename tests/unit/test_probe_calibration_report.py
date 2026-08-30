from datetime import UTC, datetime, timedelta
from pathlib import Path

from src.execution.calibration import PaperOrderObservation, TopOfBookQuote
from src.execution.execution_probe_journal import ExecutionProbeJournal
from src.execution.intent import IntentSide
from src.execution.probe_calibration_report import build_probe_calibration_report

NOW = datetime(2026, 8, 30, 10, 0, tzinfo=UTC)


def _order(order_id: str, *, rejected: bool) -> PaperOrderObservation:
    return PaperOrderObservation(
        order_id=order_id,
        symbol="ETHUSDT",
        venue="bybit-demo",
        side=IntentSide.BUY,
        requested_quantity=1.0,
        decision_timestamp_utc=NOW,
        submitted_at_utc=NOW,
        resolved_at_utc=NOW + timedelta(seconds=1),
        filled_price=0.0 if rejected else 100.5,
        filled_quantity=0.0 if rejected else 1.0,
        rejected=rejected,
        fee_cost_quote=0.0 if rejected else 0.02,
        funding_cost_quote=0.0,
    )


def _quote(offset: float, sequence: int, bid: float, ask: float) -> TopOfBookQuote:
    return TopOfBookQuote(
        symbol="ETHUSDT",
        venue="bybit-demo",
        timestamp_utc=NOW + timedelta(seconds=offset),
        source_sequence=sequence,
        bid_price=bid,
        ask_price=ask,
        bid_quantity=5.0,
        ask_quantity=5.0,
    )


def test_report_keeps_maker_fill_readiness_fail_closed(tmp_path: Path) -> None:
    path = tmp_path / "journal.sqlite3"
    journal = ExecutionProbeJournal(path)
    reference = _quote(-0.1, 1, 99.5, 100.5)
    markout = _quote(2.0, 2, 100.0, 101.0)
    journal.record_quote(probe_trade_id="trade-fill", horizon_label="REFERENCE", quote=reference)
    journal.record_quote(probe_trade_id="trade-fill", horizon_label="T+1s", quote=markout)
    journal.record_order_observation(
        probe_trade_id="trade-fill",
        probe_mode="MAKER",
        request_id="request-fill",
        observation=_order("filled", rejected=False),
        now_utc=NOW,
    )
    journal.record_order_observation(
        probe_trade_id="trade-miss",
        probe_mode="MAKER",
        request_id="request-miss",
        observation=_order("missed", rejected=True),
        now_utc=NOW,
    )

    report = build_probe_calibration_report(
        path, initial_minimum_per_bucket=2, production_minimum_per_bucket=3
    )
    eth_maker = next(
        item
        for item in report["buckets"]
        if item["symbol"] == "ETHUSDT" and item["mode"] == "MAKER"
    )

    assert report["status"] == "COLLECTING"
    assert report["initial_ready"] is False
    assert report["production_ready"] is False
    assert eth_maker["observation_count"] == 2
    assert eth_maker["fill_probability"] == 0.5
    assert eth_maker["initial_ready"] is True
    assert eth_maker["production_ready"] is False
    assert eth_maker["markouts"][0]["sample_count"] == 1
