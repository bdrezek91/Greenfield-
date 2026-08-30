from __future__ import annotations

from typing import Any

import pytest

from src.research.selective_gate_v0 import (
    SelectiveGateConfig,
    combine_period_reports,
    evaluate_selective_gate_v0,
)


def _report(
    period: str, *, mean: float = 5.0, median: float = 2.0, events: int = 40
) -> dict[str, Any]:
    return {
        "status": "EXPLORATORY_ONLY",
        "promotion_allowed": False,
        "period": period,
        "results": [
            {
                "family": "candidate_v1",
                "symbol": "ETHUSDT",
                "horizon_minutes": 60,
                "event_count": events,
                "execution_scenarios": {
                    "taker_taker": {"mean_net_bps": mean, "median_net_bps": median}
                },
            }
        ],
    }


def test_one_period_is_always_wait() -> None:
    result = evaluate_selective_gate_v0((_report("2026-07"),), risk_veto=False)

    assert result["decisions"][0]["action"] == "WAIT"
    assert result["decisions"][0]["reason"] == "INSUFFICIENT_INDEPENDENT_PERIODS"
    assert result["execution_allowed"] is False


def test_two_stable_periods_only_create_research_candidate() -> None:
    result = evaluate_selective_gate_v0(
        (_report("2026-06"), _report("2026-07", mean=4.0, median=1.0)),
        risk_veto=False,
    )

    assert result["decisions"][0]["action"] == "RESEARCH_CANDIDATE"
    assert result["decisions"][0]["worst_period_mean_net_bps"] == 4.0
    assert result["promotion_allowed"] is False


def test_one_weak_period_forces_wait() -> None:
    result = evaluate_selective_gate_v0(
        (_report("2026-06"), _report("2026-07", mean=2.9)),
        risk_veto=False,
    )

    assert result["decisions"][0]["reason"] == "MEAN_NET_EDGE_BELOW_BUFFER"


def test_risk_veto_is_always_nondiscretionary() -> None:
    result = evaluate_selective_gate_v0(
        (_report("2026-06"), _report("2026-07")),
        risk_veto=True,
    )

    assert result["decisions"][0]["reason"] == "RISK_VETO"
    assert result["ranked_research_candidates"] == []


def test_duplicate_periods_are_rejected() -> None:
    with pytest.raises(ValueError, match="independent and unique"):
        evaluate_selective_gate_v0(
            (_report("2026-07"), _report("2026-07")),
            risk_veto=False,
        )


def test_gate_cannot_be_configured_for_one_period() -> None:
    with pytest.raises(ValueError, match="at least two"):
        SelectiveGateConfig(minimum_independent_periods=1)


def test_nan_evidence_fails_closed() -> None:
    result = evaluate_selective_gate_v0(
        (_report("2026-06"), _report("2026-07", mean=float("nan"))),
        risk_veto=False,
    )

    assert result["decisions"][0]["action"] == "WAIT"
    assert result["decisions"][0]["reason"] == "INVALID_NET_EVIDENCE"


def test_multiple_strategy_reports_are_combined_by_period() -> None:
    june_second = _report("2026-06")
    july_second = _report("2026-07")
    for report in (june_second, july_second):
        report["results"][0]["family"] = "second_candidate_v1"

    combined = combine_period_reports(
        (_report("2026-07"), june_second, _report("2026-06"), july_second)
    )
    result = evaluate_selective_gate_v0(combined, risk_veto=False)

    assert result["periods"] == ["2026-06", "2026-07"]
    assert {item["family"] for item in result["ranked_research_candidates"]} == {
        "candidate_v1",
        "second_candidate_v1",
    }


def test_duplicate_identity_within_period_is_rejected() -> None:
    with pytest.raises(ValueError, match="duplicate selective gate evidence identity"):
        combine_period_reports((_report("2026-06"), _report("2026-06")))
