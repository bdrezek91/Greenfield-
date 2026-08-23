"""Champion/challenger drift monitoring and automatic degradation (Cycle 4).

Compares a promoted candidate's live SHADOW/PAPER behavior against the
research-phase expectations it was promoted with, using the same
preregistered tolerances `src.research.promotion.PromotionRegistry.
promote_to_champion` already gates on (`PaperPromotionConfig.
max_signal_frequency_deviation_pct`/`max_fill_slippage_bps`/
`min_fill_rate_pct`, `RetirementConfig.max_paper_drawdown_pct`) - this
module does not invent new thresholds, it applies the ones already
preregistered in configs/research_protocol.yaml continuously instead of
only at the one-time promotion gate.

Missing, stale, or mismatched evidence is a DEGRADED verdict, never a
skipped check - consistent with the project's fail-closed default (see
docs/GREENFIELD_V2_MASTER_PLAN.md section 2). `apply_degradation_verdict`
is the "automatic transition to WAIT": for SHADOW it activates the
existing portfolio kill switch (`ShadowRuntime.activate_safety_hold`),
which fail-closed already forces every subsequent Meta decision to
RISK_REJECTED regardless of its action - there is no separate WAIT state
to set. It also feeds the existing `PromotionRegistry.mark_degraded`,
whose auto-retire-after-N-consecutive-degraded-reviews logic already
exists in src.research.promotion; this module does not duplicate it.
Nothing here can promote a candidate - only degrade/retire it.
"""

from __future__ import annotations

import json
import math
import os
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path

from src.execution.shadow_runtime import ShadowRuntime
from src.research.config import PaperPromotionConfig, RetirementConfig
from src.research.promotion import PromotionRegistry


class DegradationVerdict(StrEnum):
    OK = "OK"
    DEGRADED = "DEGRADED"


@dataclass(frozen=True, slots=True)
class ResearchBaseline:
    signal_frequency_per_day: float
    expected_fill_rate_pct: float

    def __post_init__(self) -> None:
        if not math.isfinite(self.signal_frequency_per_day) or self.signal_frequency_per_day < 0:
            raise ValueError("research baseline signal frequency must be finite and non-negative")
        if not math.isfinite(self.expected_fill_rate_pct) or not (
            0 <= self.expected_fill_rate_pct <= 100
        ):
            raise ValueError("research baseline fill rate must be a percentage in [0, 100]")


@dataclass(frozen=True, slots=True)
class LiveObservation:
    observed_signal_frequency_per_day: float
    observed_fill_rate_pct: float
    observed_mean_slippage_bps: float | None
    observed_drawdown_pct: float
    dataset_fingerprint_matches: bool
    data_age_seconds: float | None
    max_allowed_data_staleness_seconds: float

    def __post_init__(self) -> None:
        if (
            not math.isfinite(self.observed_signal_frequency_per_day)
            or self.observed_signal_frequency_per_day < 0
        ):
            raise ValueError("observed signal frequency must be finite and non-negative")
        if not math.isfinite(self.observed_fill_rate_pct) or not (
            0 <= self.observed_fill_rate_pct <= 100
        ):
            raise ValueError("observed fill rate must be a percentage in [0, 100]")
        if self.observed_mean_slippage_bps is not None and not math.isfinite(
            self.observed_mean_slippage_bps
        ):
            raise ValueError("observed slippage must be finite when present")
        if not math.isfinite(self.observed_drawdown_pct) or self.observed_drawdown_pct < 0:
            raise ValueError("observed drawdown must be finite and non-negative")
        if self.data_age_seconds is not None and (
            not math.isfinite(self.data_age_seconds) or self.data_age_seconds < 0
        ):
            raise ValueError("data age must be finite and non-negative when present")
        if (
            not math.isfinite(self.max_allowed_data_staleness_seconds)
            or self.max_allowed_data_staleness_seconds <= 0
        ):
            raise ValueError("max allowed data staleness must be finite and positive")


@dataclass(frozen=True, slots=True)
class DriftMetric:
    name: str
    within_tolerance: bool
    detail: str


@dataclass(frozen=True, slots=True)
class DegradationReport:
    candidate_id: str
    evaluated_at_utc: datetime
    metrics: tuple[DriftMetric, ...]

    def __post_init__(self) -> None:
        if not self.candidate_id.strip():
            raise ValueError("degradation report requires a candidate id")
        if self.evaluated_at_utc.tzinfo is None:
            raise ValueError("degradation report evaluated_at_utc must be timezone-aware")
        if not self.metrics:
            raise ValueError("degradation report requires at least one metric")

    @property
    def verdict(self) -> DegradationVerdict:
        if any(not metric.within_tolerance for metric in self.metrics):
            return DegradationVerdict.DEGRADED
        return DegradationVerdict.OK

    @property
    def reasons(self) -> tuple[str, ...]:
        return tuple(metric.detail for metric in self.metrics if not metric.within_tolerance)


def evaluate_degradation(
    *,
    candidate_id: str,
    baseline: ResearchBaseline,
    observation: LiveObservation,
    promotion_config: PaperPromotionConfig,
    retirement_config: RetirementConfig,
    evaluated_at_utc: datetime,
) -> DegradationReport:
    metrics = (
        _data_drift(observation),
        _signal_drift(baseline, observation, promotion_config),
        _execution_drift_fill_rate(observation, promotion_config),
        _execution_drift_slippage(observation, promotion_config),
        _drawdown_degradation(observation, retirement_config),
    )
    return DegradationReport(
        candidate_id=candidate_id,
        evaluated_at_utc=_utc(evaluated_at_utc, "degradation evaluated_at_utc"),
        metrics=metrics,
    )


def _utc(value: datetime, name: str) -> datetime:
    if value.tzinfo is None:
        raise ValueError(f"{name} must be timezone-aware")
    return value.astimezone(UTC)


def _data_drift(observation: LiveObservation) -> DriftMetric:
    fresh = (
        observation.data_age_seconds is not None
        and observation.data_age_seconds <= observation.max_allowed_data_staleness_seconds
    )
    ok = observation.dataset_fingerprint_matches and fresh
    return DriftMetric(
        name="data_drift",
        within_tolerance=ok,
        detail=(
            "dataset fingerprint matches and data is fresh"
            if ok
            else (
                f"dataset fingerprint matches={observation.dataset_fingerprint_matches}, "
                f"data age={observation.data_age_seconds!r}s "
                f"(max {observation.max_allowed_data_staleness_seconds}s)"
            )
        ),
    )


def _signal_drift(
    baseline: ResearchBaseline,
    observation: LiveObservation,
    config: PaperPromotionConfig,
) -> DriftMetric:
    if baseline.signal_frequency_per_day <= 0:
        return DriftMetric(
            name="signal_drift",
            within_tolerance=False,
            detail="research baseline signal frequency is zero; deviation cannot be computed",
        )
    deviation_pct = (
        abs(observation.observed_signal_frequency_per_day - baseline.signal_frequency_per_day)
        / baseline.signal_frequency_per_day
        * 100.0
    )
    ok = deviation_pct <= config.max_signal_frequency_deviation_pct
    return DriftMetric(
        name="signal_drift",
        within_tolerance=ok,
        detail=(
            f"signal frequency deviation {deviation_pct:.1f}% "
            f"(baseline={baseline.signal_frequency_per_day}/day, "
            f"observed={observation.observed_signal_frequency_per_day}/day, "
            f"max {config.max_signal_frequency_deviation_pct:.1f}%)"
        ),
    )


def _execution_drift_fill_rate(
    observation: LiveObservation, config: PaperPromotionConfig
) -> DriftMetric:
    ok = observation.observed_fill_rate_pct >= config.min_fill_rate_pct
    return DriftMetric(
        name="execution_drift_fill_rate",
        within_tolerance=ok,
        detail=(
            f"observed fill rate {observation.observed_fill_rate_pct:.1f}% "
            f"(min {config.min_fill_rate_pct:.1f}%)"
        ),
    )


def _execution_drift_slippage(
    observation: LiveObservation, config: PaperPromotionConfig
) -> DriftMetric:
    ok = (
        observation.observed_mean_slippage_bps is not None
        and observation.observed_mean_slippage_bps <= config.max_fill_slippage_bps
    )
    return DriftMetric(
        name="execution_drift_slippage",
        within_tolerance=ok,
        detail=(
            f"observed mean slippage {observation.observed_mean_slippage_bps!r}bps "
            f"(max {config.max_fill_slippage_bps:.1f}bps)"
        ),
    )


def _drawdown_degradation(
    observation: LiveObservation, config: RetirementConfig
) -> DriftMetric:
    ok = observation.observed_drawdown_pct <= config.max_paper_drawdown_pct
    return DriftMetric(
        name="drawdown",
        within_tolerance=ok,
        detail=(
            f"observed drawdown {observation.observed_drawdown_pct:.1f}% "
            f"(max {config.max_paper_drawdown_pct:.1f}%)"
        ),
    )


def apply_degradation_verdict(
    report: DegradationReport,
    *,
    runtime: ShadowRuntime | None = None,
    registry: PromotionRegistry | None = None,
    retirement_config: RetirementConfig | None = None,
) -> None:
    """No-op unless `report.verdict` is DEGRADED. Never promotes anything -
    only activates the SHADOW safety hold and/or feeds the existing
    promotion registry's degrade/auto-retire path.
    """
    if report.verdict is not DegradationVerdict.DEGRADED:
        return
    reason = "; ".join(report.reasons)

    if runtime is not None:
        observation_id = f"degradation:{report.candidate_id}:{report.evaluated_at_utc.isoformat()}"
        if runtime.journal.find(observation_id) is None:
            runtime.activate_safety_hold(
                observation_id=observation_id,
                reason=reason,
                activated_at_utc=report.evaluated_at_utc,
            )

    if registry is not None and retirement_config is not None:
        registry.mark_degraded(report.candidate_id, reason, retirement_config)


class DegradationDashboardPublisher:
    """Atomic JSON + Prometheus textfile snapshot - the same pattern as
    src.execution.shadow_loop.ShadowHealthPublisher, so it slots into the
    existing node-exporter textfile collector / Grafana stack without new
    infrastructure.
    """

    def __init__(
        self, path: Path, *, now_fn: Callable[[], datetime] = lambda: datetime.now(UTC)
    ) -> None:
        self.path = Path(path)
        self.metrics_path = self.path.with_suffix(".prom")
        self._now_fn = now_fn

    def publish(self, reports: tuple[DegradationReport, ...]) -> None:
        payload = {
            "schema_version": 1,
            "candidates": [
                {
                    "candidate_id": report.candidate_id,
                    "evaluated_at_utc": report.evaluated_at_utc.astimezone(UTC).isoformat(),
                    "verdict": report.verdict.value,
                    "metrics": [
                        {
                            "name": metric.name,
                            "within_tolerance": metric.within_tolerance,
                            "detail": metric.detail,
                        }
                        for metric in report.metrics
                    ],
                }
                for report in reports
            ],
        }
        _atomic_write(self.path, json.dumps(payload, sort_keys=True, indent=2) + "\n")

        published_at = self._now_fn().astimezone(UTC).timestamp()
        lines: list[str] = [
            f"greenfield_degradation_dashboard_published_timestamp_seconds {published_at}"
        ]
        for report in reports:
            candidate_label = _escape_label(report.candidate_id)
            lines.append(
                f'greenfield_degradation_verdict{{candidate_id="{candidate_label}"}} '
                f"{1 if report.verdict is DegradationVerdict.DEGRADED else 0}"
            )
            for metric in report.metrics:
                metric_label = _escape_label(metric.name)
                lines.append(
                    "greenfield_degradation_metric_within_tolerance"
                    f'{{candidate_id="{candidate_label}",metric="{metric_label}"}} '
                    f"{1 if metric.within_tolerance else 0}"
                )
        _atomic_write(self.metrics_path, "\n".join(lines) + "\n")


def _escape_label(value: str) -> str:
    return value.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")


def _atomic_write(path: Path, value: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    try:
        with temporary.open("w", encoding="utf-8", newline="\n") as handle:
            handle.write(value)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)
