"""Transparent, causal nearest-neighbor historical analog retrieval."""

from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass

import numpy as np
import pandas as pd


@dataclass(frozen=True, slots=True)
class AnalogFamily:
    name: str
    features: tuple[str, ...]
    weight: float = 1.0

    def __post_init__(self) -> None:
        if not self.name or self.name != self.name.strip() or not self.features:
            raise ValueError("analog family requires a name and features")
        if len(set(self.features)) != len(self.features):
            raise ValueError("analog family features must be unique")
        if not math.isfinite(self.weight) or self.weight <= 0:
            raise ValueError("analog family weight must be positive")


@dataclass(frozen=True, slots=True)
class AnalogSearchConfig:
    families: tuple[AnalogFamily, ...]
    horizons_bars: tuple[int, ...] = (1, 6, 24)
    neighbor_count: int = 20
    minimum_neighbors: int = 10
    maximum_distance: float = 3.0
    minimum_quality_score: float = 0.8
    require_same_regime: bool = True

    def __post_init__(self) -> None:
        if not self.families or len({family.name for family in self.families}) != len(
            self.families
        ):
            raise ValueError("analog family names must be non-empty and unique")
        features = [feature for family in self.families for feature in family.features]
        if len(set(features)) != len(features):
            raise ValueError("one feature cannot appear in multiple analog families")
        if (
            not self.horizons_bars
            or any(horizon <= 0 for horizon in self.horizons_bars)
            or tuple(sorted(set(self.horizons_bars))) != self.horizons_bars
        ):
            raise ValueError("analog horizons must be unique positive ascending bars")
        if (
            self.neighbor_count < 1
            or self.minimum_neighbors < 1
            or self.minimum_neighbors > self.neighbor_count
            or not math.isfinite(self.maximum_distance)
            or self.maximum_distance <= 0
            or not 0 <= self.minimum_quality_score <= 1
        ):
            raise ValueError("invalid analog search thresholds")


@dataclass(frozen=True, slots=True)
class AnalogNeighbor:
    timestamp_utc: pd.Timestamp
    max_source_timestamp_utc: pd.Timestamp
    distance: float
    family_distances: dict[str, float]
    regime: str
    data_quality_score: float
    forward_returns: dict[int, float]
    adverse_returns: dict[int, float]
    favorable_returns: dict[int, float]


@dataclass(frozen=True, slots=True)
class AnalogDistribution:
    horizon_bars: int
    sample_size: int
    mean_return: float
    median_return: float
    return_q10: float
    return_q25: float
    return_q75: float
    return_q90: float
    positive_probability: float
    adverse_return_q10: float
    favorable_return_q90: float


@dataclass(frozen=True, slots=True)
class HistoricalAnalogResult:
    query_timestamp_utc: pd.Timestamp
    data_cutoff_utc: pd.Timestamp
    dataset_version: str
    code_version: str
    configuration_fingerprint: str
    regime: str
    is_meaningful: bool
    warning: str | None
    eligible_candidate_count: int
    neighbors: tuple[AnalogNeighbor, ...]
    distributions: dict[int, AnalogDistribution]


def find_historical_analogs(
    frame: pd.DataFrame,
    *,
    query_timestamp: pd.Timestamp,
    config: AnalogSearchConfig,
    dataset_version: str,
    code_version: str,
) -> HistoricalAnalogResult:
    """Find analogs whose complete configured outcomes predate the query state."""
    if not dataset_version.strip() or not code_version.strip():
        raise ValueError("analog results require dataset and code versions")
    required = {
        "timestamp",
        "max_source_timestamp",
        "close",
        "regime",
        "data_quality_score",
        *(feature for family in config.families for feature in family.features),
    }
    missing = sorted(required - set(frame.columns))
    if missing:
        raise ValueError(f"analog frame missing columns: {missing}")
    if frame.empty:
        raise ValueError("analog frame cannot be empty")
    value = frame.copy()
    value["timestamp"] = _utc_series(value["timestamp"], "timestamp")
    value["max_source_timestamp"] = _utc_series(
        value["max_source_timestamp"], "max_source_timestamp"
    )
    cutoff = _utc_timestamp(query_timestamp, "query_timestamp")
    configuration_fingerprint = _config_fingerprint(config)
    if (value["max_source_timestamp"] > value["timestamp"]).any():
        raise ValueError("analog frame contains future source timestamps")
    if value["timestamp"].duplicated().any():
        raise ValueError("analog frame contains duplicate timestamps")
    if "asset" in value and value["asset"].astype(str).str.upper().nunique() != 1:
        raise ValueError("one analog query cannot mix assets")
    value = value.sort_values("timestamp").reset_index(drop=True)
    _validate_values(value, config)

    query_candidates = value.index[value["timestamp"] <= cutoff]
    if len(query_candidates) == 0:
        raise ValueError("no state is available by the query timestamp")
    query_index = int(query_candidates[-1])
    query = value.iloc[query_index]
    if float(query["data_quality_score"]) < config.minimum_quality_score:
        return _no_analog_result(
            query=query,
            cutoff=cutoff,
            dataset_version=dataset_version,
            code_version=code_version,
            configuration_fingerprint=configuration_fingerprint,
            warning="query_quality_below_threshold",
        )
    max_horizon = max(config.horizons_bars)
    last_candidate_index = query_index - max_horizon
    if last_candidate_index < 0:
        return _no_analog_result(
            query=query,
            cutoff=cutoff,
            dataset_version=dataset_version,
            code_version=code_version,
            configuration_fingerprint=configuration_fingerprint,
            warning="insufficient_history_for_outcome_embargo",
        )

    candidates = value.iloc[: last_candidate_index + 1].copy()
    candidates = candidates.loc[
        candidates["data_quality_score"].astype(float) >= config.minimum_quality_score
    ]
    if config.require_same_regime:
        candidates = candidates.loc[candidates["regime"].astype(str) == str(query["regime"])]
    if candidates.empty:
        return _no_analog_result(
            query=query,
            cutoff=cutoff,
            dataset_version=dataset_version,
            code_version=code_version,
            configuration_fingerprint=configuration_fingerprint,
            warning="no_regime_and_quality_compatible_history",
        )

    family_distances = _family_distances(candidates, query, config)
    weights = pd.Series({family.name: family.weight for family in config.families}, dtype=float)
    squared = family_distances.pow(2).mul(weights, axis=1)
    overall_distance = np.sqrt(squared.sum(axis=1) / weights.sum())
    within_distance = pd.DataFrame({"distance": overall_distance}).loc[
        lambda data: data["distance"] <= config.maximum_distance
    ]
    eligible_count = len(within_distance)
    ranked = _select_non_overlapping(
        within_distance,
        maximum_outcome_horizon=max_horizon,
        neighbor_count=config.neighbor_count,
    )
    neighbors = tuple(
        _neighbor(
            value,
            candidate_index=int(index),
            distance=float(row["distance"]),
            family_distances=family_distances.loc[index],
            horizons=config.horizons_bars,
        )
        for index, row in ranked.iterrows()
    )
    if len(neighbors) < config.minimum_neighbors:
        return HistoricalAnalogResult(
            query_timestamp_utc=query["timestamp"],
            data_cutoff_utc=cutoff,
            dataset_version=dataset_version,
            code_version=code_version,
            configuration_fingerprint=configuration_fingerprint,
            regime=str(query["regime"]),
            is_meaningful=False,
            warning="insufficient_similar_neighbors",
            eligible_candidate_count=eligible_count,
            neighbors=neighbors,
            distributions={},
        )
    distributions = {horizon: _distribution(neighbors, horizon) for horizon in config.horizons_bars}
    return HistoricalAnalogResult(
        query_timestamp_utc=query["timestamp"],
        data_cutoff_utc=cutoff,
        dataset_version=dataset_version,
        code_version=code_version,
        configuration_fingerprint=configuration_fingerprint,
        regime=str(query["regime"]),
        is_meaningful=True,
        warning=None,
        eligible_candidate_count=eligible_count,
        neighbors=neighbors,
        distributions=distributions,
    )


def _family_distances(
    candidates: pd.DataFrame,
    query: pd.Series,
    config: AnalogSearchConfig,
) -> pd.DataFrame:
    result: dict[str, pd.Series] = {}
    for family in config.families:
        history = candidates.loc[:, family.features].astype(float)
        center = history.median(axis=0)
        mad = history.sub(center).abs().median(axis=0) * 1.4826
        fallback = history.std(axis=0, ddof=0)
        scale = mad.where(mad > 0, fallback).where(lambda item: item > 0, 1.0)
        standardized = history.sub(query.loc[list(family.features)].astype(float)).div(scale)
        result[family.name] = np.sqrt(standardized.pow(2).mean(axis=1))
    return pd.DataFrame(result, index=candidates.index)


def _select_non_overlapping(
    candidates: pd.DataFrame,
    *,
    maximum_outcome_horizon: int,
    neighbor_count: int,
) -> pd.DataFrame:
    """Greedily prevent overlapping forward paths from inflating sample size."""
    ranked = candidates.sort_values(["distance"], kind="mergesort")
    selected: list[int] = []
    for raw_index in ranked.index:
        index = int(raw_index)
        if all(abs(index - prior) > maximum_outcome_horizon for prior in selected):
            selected.append(index)
        if len(selected) >= neighbor_count:
            break
    return ranked.loc[selected]


def _neighbor(
    frame: pd.DataFrame,
    *,
    candidate_index: int,
    distance: float,
    family_distances: pd.Series,
    horizons: tuple[int, ...],
) -> AnalogNeighbor:
    row = frame.iloc[candidate_index]
    entry = float(row["close"])
    forward: dict[int, float] = {}
    adverse: dict[int, float] = {}
    favorable: dict[int, float] = {}
    for horizon in horizons:
        path = frame.iloc[candidate_index + 1 : candidate_index + horizon + 1]["close"].astype(
            float
        )
        path_returns = path / entry - 1.0
        forward[horizon] = float(path.iloc[-1] / entry - 1.0)
        adverse[horizon] = float(path_returns.min())
        favorable[horizon] = float(path_returns.max())
    return AnalogNeighbor(
        timestamp_utc=row["timestamp"],
        max_source_timestamp_utc=row["max_source_timestamp"],
        distance=distance,
        family_distances={name: float(value) for name, value in family_distances.items()},
        regime=str(row["regime"]),
        data_quality_score=float(row["data_quality_score"]),
        forward_returns=forward,
        adverse_returns=adverse,
        favorable_returns=favorable,
    )


def _distribution(neighbors: tuple[AnalogNeighbor, ...], horizon: int) -> AnalogDistribution:
    returns = np.asarray([neighbor.forward_returns[horizon] for neighbor in neighbors])
    adverse = np.asarray([neighbor.adverse_returns[horizon] for neighbor in neighbors])
    favorable = np.asarray([neighbor.favorable_returns[horizon] for neighbor in neighbors])
    return AnalogDistribution(
        horizon_bars=horizon,
        sample_size=len(neighbors),
        mean_return=float(returns.mean()),
        median_return=float(np.median(returns)),
        return_q10=float(np.quantile(returns, 0.10)),
        return_q25=float(np.quantile(returns, 0.25)),
        return_q75=float(np.quantile(returns, 0.75)),
        return_q90=float(np.quantile(returns, 0.90)),
        positive_probability=float((returns > 0).mean()),
        adverse_return_q10=float(np.quantile(adverse, 0.10)),
        favorable_return_q90=float(np.quantile(favorable, 0.90)),
    )


def _no_analog_result(
    *,
    query: pd.Series,
    cutoff: pd.Timestamp,
    dataset_version: str,
    code_version: str,
    configuration_fingerprint: str,
    warning: str,
) -> HistoricalAnalogResult:
    return HistoricalAnalogResult(
        query_timestamp_utc=query["timestamp"],
        data_cutoff_utc=cutoff,
        dataset_version=dataset_version,
        code_version=code_version,
        configuration_fingerprint=configuration_fingerprint,
        regime=str(query["regime"]),
        is_meaningful=False,
        warning=warning,
        eligible_candidate_count=0,
        neighbors=(),
        distributions={},
    )


def _validate_values(frame: pd.DataFrame, config: AnalogSearchConfig) -> None:
    features = [feature for family in config.families for feature in family.features]
    numeric = frame[["close", "data_quality_score", *features]].astype(float)
    if not np.isfinite(numeric.to_numpy()).all():
        raise ValueError("analog numeric inputs must be finite")
    if (numeric["close"] <= 0).any():
        raise ValueError("analog close prices must be positive")
    quality = numeric["data_quality_score"]
    if ((quality < 0) | (quality > 1)).any():
        raise ValueError("analog data quality must be between zero and one")
    if frame["regime"].isna().any() or (frame["regime"].astype(str).str.len() == 0).any():
        raise ValueError("analog regimes must be present")


def _config_fingerprint(config: AnalogSearchConfig) -> str:
    payload = {
        "families": [
            {
                "name": family.name,
                "features": list(family.features),
                "weight": family.weight,
            }
            for family in config.families
        ],
        "horizons_bars": list(config.horizons_bars),
        "neighbor_count": config.neighbor_count,
        "minimum_neighbors": config.minimum_neighbors,
        "maximum_distance": config.maximum_distance,
        "minimum_quality_score": config.minimum_quality_score,
        "require_same_regime": config.require_same_regime,
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()


def _utc_timestamp(value: pd.Timestamp, name: str) -> pd.Timestamp:
    timestamp = pd.Timestamp(value)
    if timestamp.tzinfo is None:
        raise ValueError(f"{name} must be timezone-aware")
    return timestamp.tz_convert("UTC")


def _utc_series(series: pd.Series, name: str) -> pd.Series:
    return pd.Series(
        [_utc_timestamp(pd.Timestamp(item), name) for item in series], index=series.index
    )
