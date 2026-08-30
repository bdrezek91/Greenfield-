"""Fail-closed multi-period research selector; it never authorizes a trade."""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True, slots=True)
class SelectiveGateConfig:
    minimum_independent_periods: int = 2
    minimum_events_per_period: int = 30
    execution_scenario: str = "taker_taker"
    minimum_mean_net_bps: float = 3.0
    minimum_median_net_bps: float = 0.0

    def __post_init__(self) -> None:
        if self.minimum_independent_periods < 2:
            raise ValueError("selective gate requires at least two independent periods")
        if self.minimum_events_per_period < 1:
            raise ValueError("selective gate requires positive event support")
        if not self.execution_scenario.strip():
            raise ValueError("selective gate requires an execution scenario")
        if not math.isfinite(self.minimum_mean_net_bps) or not math.isfinite(
            self.minimum_median_net_bps
        ):
            raise ValueError("selective gate net thresholds must be finite")


def evaluate_selective_gate_v0(
    reports: tuple[dict[str, Any], ...],
    *,
    risk_veto: bool,
    config: SelectiveGateConfig | None = None,
) -> dict[str, Any]:
    """Rank only candidates stable across every supplied independent period.

    `RESEARCH_CANDIDATE` means eligible for further falsification. It is not
    permission for SHADOW, PAPER, DEMO, or LIVE execution.
    """

    config = config or SelectiveGateConfig()
    periods = [_validated_period(report) for report in reports]
    if len(set(periods)) != len(periods):
        raise ValueError("selective gate periods must be independent and unique")
    by_period = {
        period: {_identity(row): row for row in report.get("results", [])}
        for period, report in zip(periods, reports, strict=True)
    }
    identities = sorted({identity for rows in by_period.values() for identity in rows})
    decisions = [
        _decision(identity, periods, by_period, risk_veto=risk_veto, config=config)
        for identity in identities
    ]
    candidates = [item for item in decisions if item["action"] == "RESEARCH_CANDIDATE"]
    candidates.sort(key=lambda item: item["worst_period_mean_net_bps"], reverse=True)
    return {
        "schema_version": 1,
        "gate": "SELECTIVE_GATE_V0",
        "default_action": "WAIT",
        "periods": periods,
        "risk_veto": risk_veto,
        "config": {
            "minimum_independent_periods": config.minimum_independent_periods,
            "minimum_events_per_period": config.minimum_events_per_period,
            "execution_scenario": config.execution_scenario,
            "minimum_mean_net_bps": config.minimum_mean_net_bps,
            "minimum_median_net_bps": config.minimum_median_net_bps,
        },
        "decisions": decisions,
        "ranked_research_candidates": candidates,
        "promotion_allowed": False,
        "execution_allowed": False,
    }


def combine_period_reports(
    reports: tuple[dict[str, Any], ...],
) -> tuple[dict[str, Any], ...]:
    """Combine independent strategy-family reports without merging periods."""
    grouped: dict[str, list[dict[str, Any]]] = {}
    seen: set[tuple[str, str, int, str]] = set()
    for report in reports:
        period = _validated_period(report)
        destination = grouped.setdefault(period, [])
        for row in report["results"]:
            family, symbol, horizon = _identity(row)
            key = family, symbol, horizon, period
            if key in seen:
                raise ValueError("duplicate selective gate evidence identity within period")
            seen.add(key)
            destination.append(row)
    return tuple(
        {
            "status": "EXPLORATORY_ONLY",
            "promotion_allowed": False,
            "period": period,
            "results": grouped[period],
        }
        for period in sorted(grouped)
    )


def _validated_period(report: dict[str, Any]) -> str:
    period = report.get("period")
    if not isinstance(period, str) or not period.strip():
        raise ValueError("selective gate report requires a period")
    if report.get("status") != "EXPLORATORY_ONLY" or report.get("promotion_allowed") is not False:
        raise ValueError("selective gate accepts only non-promotable exploratory reports")
    if not isinstance(report.get("results"), list):
        raise ValueError("selective gate report requires results")
    return period


def _identity(row: dict[str, Any]) -> tuple[str, str, int]:
    try:
        return str(row["family"]), str(row["symbol"]), int(row["horizon_minutes"])
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError("selective gate result has invalid identity") from exc


def _decision(
    identity: tuple[str, str, int],
    periods: list[str],
    by_period: dict[str, dict[tuple[str, str, int], dict[str, Any]]],
    *,
    risk_veto: bool,
    config: SelectiveGateConfig,
) -> dict[str, Any]:
    family, symbol, horizon = identity
    result: dict[str, Any] = {
        "family": family,
        "symbol": symbol,
        "horizon_minutes": horizon,
        "action": "WAIT",
        "reason": "",
        "period_evidence": [],
        "worst_period_mean_net_bps": None,
    }
    if risk_veto:
        result["reason"] = "RISK_VETO"
        return result
    if len(periods) < config.minimum_independent_periods:
        result["reason"] = "INSUFFICIENT_INDEPENDENT_PERIODS"
        return result
    rows = [by_period[period].get(identity) for period in periods]
    if any(row is None for row in rows):
        result["reason"] = "MISSING_PERIOD_EVIDENCE"
        return result
    evidence: list[dict[str, Any]] = []
    for period, row in zip(periods, rows, strict=True):
        assert row is not None
        scenarios = row.get("execution_scenarios")
        scenario = scenarios.get(config.execution_scenario) if isinstance(scenarios, dict) else None
        if not isinstance(scenario, dict):
            result["reason"] = "MISSING_EXECUTION_SCENARIO"
            return result
        mean_net = scenario.get("mean_net_bps")
        median_net = scenario.get("median_net_bps")
        event_count = row.get("event_count")
        if not isinstance(event_count, int) or event_count < config.minimum_events_per_period:
            result["reason"] = "INSUFFICIENT_EVENT_SUPPORT"
            return result
        if (
            not isinstance(mean_net, (int, float))
            or not isinstance(median_net, (int, float))
            or not math.isfinite(mean_net)
            or not math.isfinite(median_net)
        ):
            result["reason"] = "INVALID_NET_EVIDENCE"
            return result
        evidence.append(
            {
                "period": period,
                "event_count": event_count,
                "mean_net_bps": float(mean_net),
                "median_net_bps": float(median_net),
            }
        )
    result["period_evidence"] = evidence
    result["worst_period_mean_net_bps"] = min(item["mean_net_bps"] for item in evidence)
    if any(item["mean_net_bps"] <= config.minimum_mean_net_bps for item in evidence):
        result["reason"] = "MEAN_NET_EDGE_BELOW_BUFFER"
        return result
    if any(item["median_net_bps"] <= config.minimum_median_net_bps for item in evidence):
        result["reason"] = "MEDIAN_NET_EDGE_NOT_POSITIVE"
        return result
    result["action"] = "RESEARCH_CANDIDATE"
    result["reason"] = "MULTI_PERIOD_NET_EDGE_FOR_FALSIFICATION"
    return result
