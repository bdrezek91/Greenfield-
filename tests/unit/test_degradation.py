"""Champion/challenger drift-monitoring and auto-degradation tests."""

import json
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import Mock

import pytest

from src.research.config import PaperPromotionConfig, RetirementConfig
from src.research.degradation import (
    DegradationDashboardPublisher,
    DegradationReport,
    DegradationVerdict,
    LiveObservation,
    ResearchBaseline,
    apply_degradation_verdict,
    evaluate_degradation,
)

NOW = datetime(2026, 8, 23, 18, tzinfo=UTC)


def _promotion_config(**overrides: object) -> PaperPromotionConfig:
    fields: dict[str, object] = {
        "min_paper_weeks": 2,
        "max_paper_weeks_for_decision": 8,
        "min_paper_trades": 30,
        "max_signal_frequency_deviation_pct": 30.0,
        "max_fill_slippage_bps": 10.0,
        "min_fill_rate_pct": 90.0,
        "no_risk_limit_violations": True,
        "requires_human_approval": True,
    }
    fields.update(overrides)
    return PaperPromotionConfig(**fields)  # type: ignore[arg-type]


def _retirement_config(**overrides: object) -> RetirementConfig:
    fields: dict[str, object] = {
        "max_paper_drawdown_pct": 15.0,
        "consecutive_degraded_reviews_before_retirement": 3,
    }
    fields.update(overrides)
    return RetirementConfig(**fields)  # type: ignore[arg-type]


def _baseline(**overrides: object) -> ResearchBaseline:
    fields: dict[str, object] = {
        "signal_frequency_per_day": 4.0,
        "expected_fill_rate_pct": 95.0,
    }
    fields.update(overrides)
    return ResearchBaseline(**fields)  # type: ignore[arg-type]


def _observation(**overrides: object) -> LiveObservation:
    fields: dict[str, object] = {
        "observed_signal_frequency_per_day": 4.0,
        "observed_fill_rate_pct": 95.0,
        "observed_mean_slippage_bps": 3.0,
        "observed_drawdown_pct": 5.0,
        "dataset_fingerprint_matches": True,
        "data_age_seconds": 10.0,
        "max_allowed_data_staleness_seconds": 60.0,
    }
    fields.update(overrides)
    return LiveObservation(**fields)  # type: ignore[arg-type]


def test_research_baseline_rejects_invalid_values() -> None:
    with pytest.raises(ValueError, match="signal frequency"):
        _baseline(signal_frequency_per_day=-1.0)
    with pytest.raises(ValueError, match="fill rate"):
        _baseline(expected_fill_rate_pct=150.0)


def test_live_observation_rejects_invalid_values() -> None:
    with pytest.raises(ValueError, match="signal frequency"):
        _observation(observed_signal_frequency_per_day=-1.0)
    with pytest.raises(ValueError, match="fill rate"):
        _observation(observed_fill_rate_pct=-1.0)
    with pytest.raises(ValueError, match="drawdown"):
        _observation(observed_drawdown_pct=-1.0)
    with pytest.raises(ValueError, match="staleness"):
        _observation(max_allowed_data_staleness_seconds=0.0)


def test_all_within_tolerance_is_ok() -> None:
    report = evaluate_degradation(
        candidate_id="cand-1",
        baseline=_baseline(),
        observation=_observation(),
        promotion_config=_promotion_config(),
        retirement_config=_retirement_config(),
        evaluated_at_utc=NOW,
    )
    assert report.verdict == DegradationVerdict.OK
    assert report.reasons == ()
    assert len(report.metrics) == 6
    assert all(metric.within_tolerance for metric in report.metrics)


def test_data_drift_from_fingerprint_mismatch() -> None:
    report = evaluate_degradation(
        candidate_id="cand-1",
        baseline=_baseline(),
        observation=_observation(dataset_fingerprint_matches=False),
        promotion_config=_promotion_config(),
        retirement_config=_retirement_config(),
        evaluated_at_utc=NOW,
    )
    assert report.verdict == DegradationVerdict.DEGRADED
    data_metric = next(m for m in report.metrics if m.name == "data_drift")
    assert not data_metric.within_tolerance


def test_data_drift_from_stale_data() -> None:
    report = evaluate_degradation(
        candidate_id="cand-1",
        baseline=_baseline(),
        observation=_observation(data_age_seconds=120.0, max_allowed_data_staleness_seconds=60.0),
        promotion_config=_promotion_config(),
        retirement_config=_retirement_config(),
        evaluated_at_utc=NOW,
    )
    assert report.verdict == DegradationVerdict.DEGRADED


def test_data_drift_from_missing_freshness_is_fail_closed() -> None:
    report = evaluate_degradation(
        candidate_id="cand-1",
        baseline=_baseline(),
        observation=_observation(data_age_seconds=None),
        promotion_config=_promotion_config(),
        retirement_config=_retirement_config(),
        evaluated_at_utc=NOW,
    )
    assert report.verdict == DegradationVerdict.DEGRADED


def test_signal_drift_exceeds_tolerance() -> None:
    report = evaluate_degradation(
        candidate_id="cand-1",
        baseline=_baseline(signal_frequency_per_day=4.0),
        observation=_observation(observed_signal_frequency_per_day=8.0),  # +100% deviation
        promotion_config=_promotion_config(max_signal_frequency_deviation_pct=30.0),
        retirement_config=_retirement_config(),
        evaluated_at_utc=NOW,
    )
    assert report.verdict == DegradationVerdict.DEGRADED
    signal_metric = next(m for m in report.metrics if m.name == "signal_drift")
    assert not signal_metric.within_tolerance


def test_signal_drift_zero_baseline_is_fail_closed() -> None:
    report = evaluate_degradation(
        candidate_id="cand-1",
        baseline=_baseline(signal_frequency_per_day=0.0),
        observation=_observation(),
        promotion_config=_promotion_config(),
        retirement_config=_retirement_config(),
        evaluated_at_utc=NOW,
    )
    signal_metric = next(m for m in report.metrics if m.name == "signal_drift")
    assert not signal_metric.within_tolerance


def test_execution_drift_fill_rate_breach() -> None:
    report = evaluate_degradation(
        candidate_id="cand-1",
        baseline=_baseline(),
        observation=_observation(observed_fill_rate_pct=50.0),
        promotion_config=_promotion_config(min_fill_rate_pct=90.0),
        retirement_config=_retirement_config(),
        evaluated_at_utc=NOW,
    )
    assert report.verdict == DegradationVerdict.DEGRADED


def test_execution_drift_fill_rate_absolute_floor_binds_independently_of_baseline() -> None:
    """Observed fill rate clears the candidate's own research baseline but
    breaches the protocol-wide absolute floor - only the absolute-floor
    metric should catch it."""
    report = evaluate_degradation(
        candidate_id="cand-1",
        baseline=_baseline(expected_fill_rate_pct=80.0),
        observation=_observation(observed_fill_rate_pct=85.0),
        promotion_config=_promotion_config(min_fill_rate_pct=90.0),
        retirement_config=_retirement_config(),
        evaluated_at_utc=NOW,
    )
    assert report.verdict == DegradationVerdict.DEGRADED
    floor_metric = next(m for m in report.metrics if m.name == "execution_drift_fill_rate")
    baseline_metric = next(
        m for m in report.metrics if m.name == "execution_drift_fill_rate_vs_baseline"
    )
    assert not floor_metric.within_tolerance
    assert baseline_metric.within_tolerance


def test_execution_drift_fill_rate_vs_baseline_binds_independently_of_absolute_floor() -> None:
    """Observed fill rate clears the protocol-wide absolute floor but has
    dropped below what this candidate's own research baseline predicted -
    only the baseline-comparison metric should catch it."""
    report = evaluate_degradation(
        candidate_id="cand-1",
        baseline=_baseline(expected_fill_rate_pct=98.0),
        observation=_observation(observed_fill_rate_pct=92.0),
        promotion_config=_promotion_config(min_fill_rate_pct=90.0),
        retirement_config=_retirement_config(),
        evaluated_at_utc=NOW,
    )
    assert report.verdict == DegradationVerdict.DEGRADED
    floor_metric = next(m for m in report.metrics if m.name == "execution_drift_fill_rate")
    baseline_metric = next(
        m for m in report.metrics if m.name == "execution_drift_fill_rate_vs_baseline"
    )
    assert floor_metric.within_tolerance
    assert not baseline_metric.within_tolerance


def test_execution_drift_slippage_breach() -> None:
    report = evaluate_degradation(
        candidate_id="cand-1",
        baseline=_baseline(),
        observation=_observation(observed_mean_slippage_bps=50.0),
        promotion_config=_promotion_config(max_fill_slippage_bps=10.0),
        retirement_config=_retirement_config(),
        evaluated_at_utc=NOW,
    )
    assert report.verdict == DegradationVerdict.DEGRADED


def test_execution_drift_slippage_missing_is_fail_closed() -> None:
    report = evaluate_degradation(
        candidate_id="cand-1",
        baseline=_baseline(),
        observation=_observation(observed_mean_slippage_bps=None),
        promotion_config=_promotion_config(),
        retirement_config=_retirement_config(),
        evaluated_at_utc=NOW,
    )
    assert report.verdict == DegradationVerdict.DEGRADED


def test_drawdown_breach() -> None:
    report = evaluate_degradation(
        candidate_id="cand-1",
        baseline=_baseline(),
        observation=_observation(observed_drawdown_pct=25.0),
        promotion_config=_promotion_config(),
        retirement_config=_retirement_config(max_paper_drawdown_pct=15.0),
        evaluated_at_utc=NOW,
    )
    assert report.verdict == DegradationVerdict.DEGRADED


def test_degradation_report_requires_timezone_aware_timestamp_and_metrics() -> None:
    with pytest.raises(ValueError, match="candidate id"):
        DegradationReport(candidate_id="  ", evaluated_at_utc=NOW, metrics=())
    from src.research.degradation import DriftMetric

    metric = DriftMetric(name="x", within_tolerance=True, detail="ok")
    with pytest.raises(ValueError, match="timezone-aware"):
        DegradationReport(
            candidate_id="cand-1",
            evaluated_at_utc=datetime(2026, 8, 23, 18),
            metrics=(metric,),
        )
    with pytest.raises(ValueError, match="at least one metric"):
        DegradationReport(candidate_id="cand-1", evaluated_at_utc=NOW, metrics=())


def test_apply_degradation_verdict_is_a_noop_when_ok() -> None:
    report = evaluate_degradation(
        candidate_id="cand-1",
        baseline=_baseline(),
        observation=_observation(),
        promotion_config=_promotion_config(),
        retirement_config=_retirement_config(),
        evaluated_at_utc=NOW,
    )
    runtime = Mock()
    registry = Mock()
    apply_degradation_verdict(
        report, runtime=runtime, registry=registry, retirement_config=_retirement_config()
    )
    runtime.activate_safety_hold.assert_not_called()
    registry.mark_degraded.assert_not_called()


def test_apply_degradation_verdict_activates_safety_hold_and_marks_degraded() -> None:
    report = evaluate_degradation(
        candidate_id="cand-1",
        baseline=_baseline(),
        observation=_observation(dataset_fingerprint_matches=False),
        promotion_config=_promotion_config(),
        retirement_config=_retirement_config(),
        evaluated_at_utc=NOW,
    )
    runtime = Mock()
    runtime.journal.find.return_value = None
    registry = Mock()
    retirement_config = _retirement_config()

    apply_degradation_verdict(
        report, runtime=runtime, registry=registry, retirement_config=retirement_config
    )

    runtime.activate_safety_hold.assert_called_once()
    call_kwargs = runtime.activate_safety_hold.call_args.kwargs
    assert call_kwargs["observation_id"] == f"degradation:cand-1:{NOW.isoformat()}"
    assert "fingerprint" in call_kwargs["reason"] or "data" in call_kwargs["reason"]
    registry.mark_degraded.assert_called_once_with(
        "cand-1", call_kwargs["reason"], retirement_config
    )


def test_apply_degradation_verdict_is_idempotent_for_the_same_evaluation() -> None:
    report = evaluate_degradation(
        candidate_id="cand-1",
        baseline=_baseline(),
        observation=_observation(dataset_fingerprint_matches=False),
        promotion_config=_promotion_config(),
        retirement_config=_retirement_config(),
        evaluated_at_utc=NOW,
    )
    runtime = Mock()
    runtime.journal.find.return_value = object()  # already recorded
    apply_degradation_verdict(report, runtime=runtime, registry=None, retirement_config=None)
    runtime.activate_safety_hold.assert_not_called()


def test_dashboard_publisher_writes_json_and_prom(tmp_path: Path) -> None:
    ok_report = evaluate_degradation(
        candidate_id="cand-ok",
        baseline=_baseline(),
        observation=_observation(),
        promotion_config=_promotion_config(),
        retirement_config=_retirement_config(),
        evaluated_at_utc=NOW,
    )
    degraded_report = evaluate_degradation(
        candidate_id="cand-bad",
        baseline=_baseline(),
        observation=_observation(observed_drawdown_pct=99.0),
        promotion_config=_promotion_config(),
        retirement_config=_retirement_config(),
        evaluated_at_utc=NOW,
    )
    publisher = DegradationDashboardPublisher(tmp_path / "dashboard.json", now_fn=lambda: NOW)
    publisher.publish((ok_report, degraded_report))

    payload = json.loads(publisher.path.read_text(encoding="utf-8"))
    verdicts = {c["candidate_id"]: c["verdict"] for c in payload["candidates"]}
    assert verdicts == {"cand-ok": "OK", "cand-bad": "DEGRADED"}

    prom_text = publisher.metrics_path.read_text(encoding="utf-8")
    assert 'greenfield_degradation_verdict{candidate_id="cand-ok"} 0' in prom_text
    assert 'greenfield_degradation_verdict{candidate_id="cand-bad"} 1' in prom_text
    assert (
        f"greenfield_degradation_dashboard_published_timestamp_seconds {NOW.timestamp()}"
        in prom_text
    )
