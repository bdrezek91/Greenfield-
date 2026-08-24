"""Point-in-time dependence audit for confirmation-family evidence.

Different ``ConfirmationFamily`` labels are an architectural partition, not
proof of statistical independence.  This module produces the versioned,
fail-closed research artifact required before a multi-family candidate can be
promoted.  Absolute correlation is used because strongly inverse signals are
duplicates too.
"""

from __future__ import annotations

import json
import math
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from itertools import combinations
from pathlib import Path

import pandas as pd
import yaml

from src.engines.contracts import ConfirmationFamily

DEFAULT_CONFIG_PATH = (
    Path(__file__).resolve().parents[2] / "configs" / "confirmation_independence.yaml"
)


class ConfirmationIndependenceError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class ConfirmationIndependenceConfig:
    version: int
    min_pair_observations: int
    max_absolute_spearman: float
    rolling_window_observations: int
    max_rolling_absolute_spearman: float
    min_regime_observations: int

    def __post_init__(self) -> None:
        if self.version <= 0:
            raise ConfirmationIndependenceError("config version must be positive")
        if self.min_pair_observations < 3 or self.min_regime_observations < 3:
            raise ConfirmationIndependenceError("observation thresholds must be at least three")
        if self.rolling_window_observations < 3:
            raise ConfirmationIndependenceError("rolling window must be at least three")
        if not 0 < self.max_absolute_spearman < 1:
            raise ConfirmationIndependenceError("absolute Spearman threshold must be in (0, 1)")
        if not 0 < self.max_rolling_absolute_spearman < 1:
            raise ConfirmationIndependenceError(
                "rolling absolute Spearman threshold must be in (0, 1)"
            )


@dataclass(frozen=True, slots=True)
class FamilyPairDependence:
    family_a: str
    family_b: str
    observations: int
    spearman: float | None
    max_rolling_absolute_spearman: float | None
    max_regime_absolute_spearman: float | None
    status: str
    reasons: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class ConfirmationIndependenceReport:
    schema_version: int
    config_version: int
    as_of_utc: str
    families: tuple[str, ...]
    status: str
    pairs: tuple[FamilyPairDependence, ...]


def load_confirmation_independence_config(
    path: Path = DEFAULT_CONFIG_PATH,
) -> ConfirmationIndependenceConfig:
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    return ConfirmationIndependenceConfig(**raw)


def evaluate_confirmation_independence(
    frame: pd.DataFrame,
    *,
    as_of_utc: datetime,
    config: ConfirmationIndependenceConfig | None = None,
) -> ConfirmationIndependenceReport:
    config = config or load_confirmation_independence_config()
    if as_of_utc.tzinfo is None:
        raise ConfirmationIndependenceError("as_of_utc must be timezone-aware")
    as_of = pd.Timestamp(as_of_utc.astimezone(UTC))
    required = {"timestamp", "max_source_timestamp", "regime"}
    missing = required - set(frame.columns)
    if missing:
        raise ConfirmationIndependenceError(f"missing columns: {sorted(missing)}")
    family_columns = tuple(
        family.value for family in ConfirmationFamily if family.value in frame.columns
    )
    if len(family_columns) < 2:
        raise ConfirmationIndependenceError("at least two confirmation families are required")

    data = frame.copy()
    data["timestamp"] = pd.to_datetime(data["timestamp"], utc=True)
    data["max_source_timestamp"] = pd.to_datetime(data["max_source_timestamp"], utc=True)
    if data["timestamp"].duplicated().any():
        raise ConfirmationIndependenceError("timestamps must be unique")
    if (data["timestamp"] > as_of).any() or (
        data["max_source_timestamp"] > data["timestamp"]
    ).any():
        raise ConfirmationIndependenceError("future information is forbidden")
    data = data.sort_values("timestamp", kind="mergesort")

    pairs = tuple(
        _evaluate_pair(data, family_a, family_b, config)
        for family_a, family_b in combinations(family_columns, 2)
    )
    if any(pair.status == "FAIL" for pair in pairs):
        status = "FAIL"
    elif any(pair.status == "INSUFFICIENT_DATA" for pair in pairs):
        status = "INSUFFICIENT_DATA"
    else:
        status = "PASS"
    return ConfirmationIndependenceReport(
        schema_version=1,
        config_version=config.version,
        as_of_utc=as_of.isoformat(),
        families=family_columns,
        status=status,
        pairs=pairs,
    )


def _evaluate_pair(
    data: pd.DataFrame,
    family_a: str,
    family_b: str,
    config: ConfirmationIndependenceConfig,
) -> FamilyPairDependence:
    pair = data[[family_a, family_b, "regime"]].dropna()
    observations = len(pair)
    if observations < config.min_pair_observations:
        return FamilyPairDependence(
            family_a, family_b, observations, None, None, None,
            "INSUFFICIENT_DATA", ("PAIR_SAMPLE_TOO_SMALL",),
        )
    spearman = float(pair[family_a].corr(pair[family_b], method="spearman"))
    rolling = []
    for start in range(0, observations - config.rolling_window_observations + 1):
        window = pair.iloc[start : start + config.rolling_window_observations]
        value = float(window[family_a].corr(window[family_b], method="spearman"))
        if math.isfinite(value):
            rolling.append(abs(value))
    regime_values = []
    for _, regime_frame in pair.groupby("regime", sort=True):
        if len(regime_frame) >= config.min_regime_observations:
            value = float(regime_frame[family_a].corr(regime_frame[family_b], method="spearman"))
            if math.isfinite(value):
                regime_values.append(abs(value))
    max_rolling = max(rolling) if rolling else None
    max_regime = max(regime_values) if regime_values else None
    reasons = []
    if abs(spearman) > config.max_absolute_spearman:
        reasons.append("FULL_SAMPLE_DEPENDENCE")
    if max_rolling is not None and max_rolling > config.max_rolling_absolute_spearman:
        reasons.append("ROLLING_WINDOW_DEPENDENCE")
    if max_regime is not None and max_regime > config.max_rolling_absolute_spearman:
        reasons.append("REGIME_DEPENDENCE")
    return FamilyPairDependence(
        family_a=family_a,
        family_b=family_b,
        observations=observations,
        spearman=spearman,
        max_rolling_absolute_spearman=max_rolling,
        max_regime_absolute_spearman=max_regime,
        status="FAIL" if reasons else "PASS",
        reasons=tuple(reasons),
    )


def require_independence_for_promotion(
    report: ConfirmationIndependenceReport,
    *,
    required_families: tuple[ConfirmationFamily, ...],
) -> None:
    required = {family.value for family in required_families}
    if report.status != "PASS":
        raise ConfirmationIndependenceError(
            f"confirmation independence is not promotion-eligible: {report.status}"
        )
    if not required.issubset(report.families):
        raise ConfirmationIndependenceError("independence report does not cover every family")


def write_confirmation_independence_report(
    report: ConfirmationIndependenceReport, path: Path
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(asdict(report), indent=2, sort_keys=True) + "\n"
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(payload, encoding="utf-8")
    temporary.replace(path)
