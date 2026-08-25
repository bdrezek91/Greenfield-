"""Point-in-time outcome labeling for the durable Demo ATAS/MC journal."""

from __future__ import annotations

import json
import math
import os
import uuid
from dataclasses import asdict, dataclass
from datetime import timedelta
from pathlib import Path

from src.execution.demo_signal_journal import DemoSignalJournalEntry


@dataclass(frozen=True, slots=True)
class DemoSignalHorizonSummary:
    horizon_seconds: int
    labeled_observation_count: int
    actionable_count: int
    profitable_action_count: int
    mean_directional_return_bps: float | None
    median_directional_return_bps: float | None


@dataclass(frozen=True, slots=True)
class DemoSignalValidationReport:
    schema_version: int
    qualified: bool
    source_observation_count: int
    eligible_observation_count: int
    minimum_required_observations: int
    family_observation_counts: dict[str, int]
    momentum_veto_counts: dict[str, int]
    experimental_action_counts: dict[str, int]
    horizons: tuple[DemoSignalHorizonSummary, ...]
    reasons: tuple[str, ...]

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


def validate_demo_signals(
    entries: tuple[DemoSignalJournalEntry, ...],
    *,
    horizons_seconds: tuple[int, ...] = (60, 300, 600),
    minimum_observations: int = 1_000,
) -> DemoSignalValidationReport:
    if (
        not horizons_seconds
        or any(item <= 0 for item in horizons_seconds)
        or len(set(horizons_seconds)) != len(horizons_seconds)
        or minimum_observations <= 0
    ):
        raise ValueError("invalid Demo signal validation configuration")
    ordered = tuple(sorted(entries, key=lambda item: (item.observed_at_utc, item.observation_id)))
    eligible = tuple(
        item for item in ordered if not item.operator_forced and item.market_price is not None
    )
    family_counts: dict[str, int] = {}
    momentum_counts: dict[str, int] = {}
    action_counts: dict[str, int] = {}
    for entry in eligible:
        momentum_counts[entry.momentum_veto] = momentum_counts.get(entry.momentum_veto, 0) + 1
        action_counts[entry.experimental_action] = (
            action_counts.get(entry.experimental_action, 0) + 1
        )
        evidence = json.loads(entry.evidence_json)
        if not isinstance(evidence, list):
            raise ValueError("Demo signal evidence must be a list")
        for item in evidence:
            if not isinstance(item, dict) or not isinstance(item.get("family"), str):
                raise ValueError("Demo signal evidence family is invalid")
            family = str(item["family"])
            family_counts[family] = family_counts.get(family, 0) + 1
    summaries = tuple(
        _horizon_summary(eligible, horizon_seconds=item) for item in horizons_seconds
    )
    reasons = []
    if len(eligible) < minimum_observations:
        reasons.append("INSUFFICIENT_OBSERVATIONS")
    if any(item.labeled_observation_count < minimum_observations for item in summaries):
        reasons.append("INSUFFICIENT_MATURED_OUTCOMES")
    if not any(item.actionable_count for item in summaries):
        reasons.append("NO_ACTIONABLE_SIGNALS")
    return DemoSignalValidationReport(
        schema_version=1,
        qualified=not reasons,
        source_observation_count=len(entries),
        eligible_observation_count=len(eligible),
        minimum_required_observations=minimum_observations,
        family_observation_counts=dict(sorted(family_counts.items())),
        momentum_veto_counts=dict(sorted(momentum_counts.items())),
        experimental_action_counts=dict(sorted(action_counts.items())),
        horizons=summaries,
        reasons=tuple(reasons),
    )


def write_demo_signal_validation_report(
    path: Path, report: DemoSignalValidationReport
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    value = json.dumps(report.to_dict(), sort_keys=True, indent=2, allow_nan=False) + "\n"
    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    try:
        with temporary.open("x", encoding="utf-8", newline="\n") as handle:
            handle.write(value)
            handle.flush()
            os.fsync(handle.fileno())
        os.link(temporary, path)
    except FileExistsError as exc:
        raise FileExistsError(
            f"Demo signal validation report exists and will not be overwritten: {path}"
        ) from exc
    finally:
        temporary.unlink(missing_ok=True)


def _horizon_summary(
    entries: tuple[DemoSignalJournalEntry, ...], *, horizon_seconds: int
) -> DemoSignalHorizonSummary:
    labeled = []
    actionable = []
    for index, entry in enumerate(entries):
        target = entry.observed_at_utc + timedelta(seconds=horizon_seconds)
        future = next(
            (
                item
                for item in entries[index + 1 :]
                if item.symbol == entry.symbol
                and item.observed_at_utc >= target
                and item.market_price is not None
            ),
            None,
        )
        if future is None:
            continue
        assert entry.market_price is not None and future.market_price is not None
        raw_bps = (future.market_price / entry.market_price - 1.0) * 10_000
        if not math.isfinite(raw_bps):
            raise ValueError("non-finite Demo signal outcome")
        labeled.append(raw_bps)
        if entry.experimental_action == "LONG":
            actionable.append(raw_bps)
        elif entry.experimental_action == "SHORT":
            actionable.append(-raw_bps)
    ordered_returns = sorted(actionable)
    median = None
    if ordered_returns:
        middle = len(ordered_returns) // 2
        median = (
            ordered_returns[middle]
            if len(ordered_returns) % 2
            else (ordered_returns[middle - 1] + ordered_returns[middle]) / 2
        )
    return DemoSignalHorizonSummary(
        horizon_seconds=horizon_seconds,
        labeled_observation_count=len(labeled),
        actionable_count=len(actionable),
        profitable_action_count=sum(item > 0 for item in actionable),
        mean_directional_return_bps=(sum(actionable) / len(actionable) if actionable else None),
        median_directional_return_bps=median,
    )
