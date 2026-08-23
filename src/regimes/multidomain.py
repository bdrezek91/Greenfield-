"""Causal, auditable multi-domain market regime classification."""

from __future__ import annotations

import math
from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from src.regimes.classifier import RegimeConfig, classify_regimes


@dataclass(frozen=True, slots=True)
class MultiDomainRegimeConfig:
    price: RegimeConfig = field(default_factory=RegimeConfig)
    rolling_window: int = 48
    confirmation_bars: int = 3
    liquidity_stress_z: float = 1.0
    flow_state_z: float = 0.75
    liquidation_cascade_z: float = 1.5
    fragmentation_z: float = 1.5
    risk_breadth_threshold: float = 2.0 / 3.0

    def __post_init__(self) -> None:
        if self.rolling_window < 3 or self.confirmation_bars < 1:
            raise ValueError("invalid multi-domain regime window configuration")
        if (
            self.liquidity_stress_z <= 0
            or self.flow_state_z <= 0
            or self.liquidation_cascade_z <= 0
            or self.fragmentation_z <= 0
            or not 0.5 < self.risk_breadth_threshold < 1
        ):
            raise ValueError("invalid multi-domain regime thresholds")


def classify_multidomain_regimes(
    frame: pd.DataFrame,
    config: MultiDomainRegimeConfig | None = None,
) -> pd.DataFrame:
    """Classify independent price, volatility, liquidity, flow, and risk domains.

    The input must already be point-in-time aligned. A row's
    ``max_source_timestamp`` proves the latest evidence used at that decision
    time. Missing or future evidence fails closed rather than receiving a
    guessed regime.
    """
    config = config or MultiDomainRegimeConfig()
    required = {
        "timestamp",
        "max_source_timestamp",
        "high",
        "low",
        "close",
        "realized_volatility",
        "spread_bps",
        "depth_notional",
        "signed_delta",
        "open_interest",
        "liquidation_total",
        "market_breadth_positive_fraction",
        "cross_asset_return_dispersion",
        "benchmark_return",
    }
    missing = sorted(required - set(frame.columns))
    if missing:
        raise ValueError(f"multi-domain regime frame missing columns: {missing}")
    if frame.empty:
        return _empty_result(frame)

    value = frame.copy()
    value["timestamp"] = _utc_series(value["timestamp"], "timestamp")
    value["max_source_timestamp"] = _utc_series(
        value["max_source_timestamp"], "max_source_timestamp"
    )
    if (value["max_source_timestamp"] > value["timestamp"]).any():
        raise ValueError("multi-domain regime frame contains future source timestamps")
    group_columns = ["timestamp"]
    if "asset" in value:
        value["asset"] = value["asset"].astype(str).str.upper()
        group_columns.append("asset")
    if value.duplicated(group_columns).any():
        raise ValueError("multi-domain regime frame contains duplicate observations")
    _validate_numeric_inputs(value)

    if "asset" not in value:
        return _classify_one(value.sort_values("timestamp"), config).reset_index(drop=True)
    groups = [
        _classify_one(group.sort_values("timestamp"), config)
        for _, group in value.groupby("asset", sort=True)
    ]
    return (
        pd.concat(groups, ignore_index=True)
        .sort_values(["timestamp", "asset"])
        .reset_index(drop=True)
    )


def stabilize_regime_labels(candidates: pd.Series, *, confirmation_bars: int) -> pd.Series:
    """Apply causal switch confirmation while retaining the prior stable state."""
    if confirmation_bars < 1:
        raise ValueError("confirmation_bars must be positive")
    stable: str | None = None
    pending: str | None = None
    pending_count = 0
    output: list[object] = []
    for raw_candidate in candidates:
        if pd.isna(raw_candidate):
            output.append(pd.NA)
            stable = None
            pending = None
            pending_count = 0
            continue
        candidate = str(raw_candidate)
        if candidate == stable:
            pending = None
            pending_count = 0
        elif candidate == pending:
            pending_count += 1
        else:
            pending = candidate
            pending_count = 1
        if pending_count >= confirmation_bars:
            stable = candidate
            pending = None
            pending_count = 0
        output.append(pd.NA if stable is None else stable)
    return pd.Series(output, index=candidates.index, dtype="object")


def _classify_one(frame: pd.DataFrame, config: MultiDomainRegimeConfig) -> pd.DataFrame:
    out = frame.copy()
    price = classify_regimes(out, config.price)
    out["adx"] = price["adx"]
    out["atr"] = price["atr"]
    out["trend_regime_candidate"] = price["trend_regime"]

    window = config.rolling_window
    volatility = out["realized_volatility"].astype(float)
    vol_low = volatility.rolling(window, min_periods=window).quantile(1.0 / 3.0)
    vol_high = volatility.rolling(window, min_periods=window).quantile(2.0 / 3.0)
    out["volatility_low_threshold"] = vol_low
    out["volatility_high_threshold"] = vol_high
    out["volatility_regime_candidate"] = _volatility_candidate(volatility, vol_low, vol_high)

    spread_z = _rolling_zscore(out["spread_bps"].astype(float), window)
    depth_z = _rolling_zscore(out["depth_notional"].astype(float), window)
    liquidity_z = pd.concat([spread_z, -depth_z], axis=1).mean(axis=1, skipna=False)
    out["liquidity_stress_score"] = _sigmoid(liquidity_z - config.liquidity_stress_z)
    out["liquidity_regime_candidate"] = _binary_candidate(
        liquidity_z,
        threshold=config.liquidity_stress_z,
        high="STRESSED",
        low="LIQUID",
    )

    price_return = out["close"].astype(float).pct_change(fill_method=None)
    oi_change = out["open_interest"].astype(float).pct_change(fill_method=None)
    return_z = _rolling_zscore(price_return, window)
    delta_z = _rolling_zscore(out["signed_delta"].astype(float), window)
    oi_z = _rolling_zscore(oi_change, window)
    liquidation_z = _rolling_zscore(out["liquidation_total"].astype(float), window)
    directional_flow_z = pd.concat([return_z, delta_z, oi_z], axis=1).mean(axis=1, skipna=False)
    deleveraging_z = pd.concat([-return_z, -oi_z, liquidation_z], axis=1).mean(axis=1, skipna=False)
    out["directional_flow_score"] = directional_flow_z
    out["deleveraging_score"] = deleveraging_z
    out["liquidation_intensity_zscore"] = liquidation_z
    out["flow_regime_candidate"] = _flow_candidate(
        directional_flow_z,
        deleveraging_z,
        liquidation_z,
        config=config,
    )

    dispersion_z = _rolling_zscore(out["cross_asset_return_dispersion"].astype(float), window)
    breadth = out["market_breadth_positive_fraction"].astype(float)
    benchmark_return = out["benchmark_return"].astype(float)
    out["fragmentation_zscore"] = dispersion_z
    out["cross_market_regime_candidate"] = _cross_market_candidate(
        breadth,
        benchmark_return,
        dispersion_z,
        config=config,
    )

    for domain in ("trend", "volatility", "liquidity", "flow", "cross_market"):
        out[f"{domain}_regime"] = stabilize_regime_labels(
            out[f"{domain}_regime_candidate"],
            confirmation_bars=config.confirmation_bars,
        )
    return out


def _volatility_candidate(value: pd.Series, low: pd.Series, high: pd.Series) -> pd.Series:
    candidate = pd.Series(pd.NA, index=value.index, dtype="object")
    ready = low.notna() & high.notna()
    candidate.loc[ready & (value <= low)] = "LOW_VOL"
    candidate.loc[ready & (value > low) & (value < high)] = "NORMAL_VOL"
    candidate.loc[ready & (value >= high)] = "HIGH_VOL"
    return candidate


def _binary_candidate(score: pd.Series, *, threshold: float, high: str, low: str) -> pd.Series:
    candidate = pd.Series(pd.NA, index=score.index, dtype="object")
    candidate.loc[score.notna() & (score >= threshold)] = high
    candidate.loc[score.notna() & (score < threshold)] = low
    return candidate


def _flow_candidate(
    directional: pd.Series,
    deleveraging: pd.Series,
    liquidation: pd.Series,
    *,
    config: MultiDomainRegimeConfig,
) -> pd.Series:
    candidate = pd.Series(pd.NA, index=directional.index, dtype="object")
    ready = directional.notna() & deleveraging.notna() & liquidation.notna()
    candidate.loc[ready] = "BALANCED"
    candidate.loc[ready & (directional >= config.flow_state_z)] = "ACCUMULATION"
    candidate.loc[ready & (directional <= -config.flow_state_z)] = "DISTRIBUTION"
    candidate.loc[ready & (deleveraging >= config.flow_state_z)] = "DELEVERAGING"
    candidate.loc[
        ready
        & (deleveraging >= config.flow_state_z)
        & (liquidation >= config.liquidation_cascade_z)
    ] = "LIQUIDATION_CASCADE"
    return candidate


def _cross_market_candidate(
    breadth: pd.Series,
    benchmark_return: pd.Series,
    dispersion_z: pd.Series,
    *,
    config: MultiDomainRegimeConfig,
) -> pd.Series:
    candidate = pd.Series(pd.NA, index=breadth.index, dtype="object")
    ready = breadth.notna() & benchmark_return.notna() & dispersion_z.notna()
    candidate.loc[ready] = "NEUTRAL"
    threshold = config.risk_breadth_threshold
    candidate.loc[ready & (breadth >= threshold) & (benchmark_return > 0)] = "RISK_ON"
    candidate.loc[ready & (breadth <= 1.0 - threshold) & (benchmark_return < 0)] = "RISK_OFF"
    candidate.loc[ready & (dispersion_z >= config.fragmentation_z)] = "FRAGMENTED"
    return candidate


def _rolling_zscore(value: pd.Series, window: int) -> pd.Series:
    mean = value.rolling(window, min_periods=window).mean()
    standard_deviation = value.rolling(window, min_periods=window).std(ddof=0)
    return (value - mean) / standard_deviation.replace(0, np.nan)


def _sigmoid(value: pd.Series) -> pd.Series:
    return value.map(lambda item: 1.0 / (1.0 + math.exp(-item)) if pd.notna(item) else np.nan)


def _utc_series(series: pd.Series, name: str) -> pd.Series:
    parsed: list[pd.Timestamp] = []
    for item in series:
        timestamp = pd.Timestamp(item)
        if timestamp.tzinfo is None:
            raise ValueError(f"{name} must be timezone-aware")
        parsed.append(timestamp.tz_convert("UTC"))
    return pd.Series(parsed, index=series.index)


def _validate_numeric_inputs(frame: pd.DataFrame) -> None:
    columns = [
        "high",
        "low",
        "close",
        "realized_volatility",
        "spread_bps",
        "depth_notional",
        "signed_delta",
        "open_interest",
        "liquidation_total",
        "market_breadth_positive_fraction",
        "cross_asset_return_dispersion",
        "benchmark_return",
    ]
    numeric = frame[columns].astype(float)
    if not np.isfinite(numeric.to_numpy()).all():
        raise ValueError("multi-domain regime inputs must be finite")
    if (numeric[["high", "low", "close", "depth_notional", "open_interest"]] <= 0).any().any():
        raise ValueError("multi-domain prices, depth, and OI must be positive")
    if (
        (
            numeric[
                [
                    "realized_volatility",
                    "spread_bps",
                    "liquidation_total",
                    "cross_asset_return_dispersion",
                ]
            ]
            < 0
        )
        .any()
        .any()
    ):
        raise ValueError("multi-domain magnitudes must be non-negative")
    breadth = numeric["market_breadth_positive_fraction"]
    if ((breadth < 0) | (breadth > 1)).any():
        raise ValueError("market breadth must be between zero and one")


def _empty_result(frame: pd.DataFrame) -> pd.DataFrame:
    result = frame.copy()
    for domain in ("trend", "volatility", "liquidity", "flow", "cross_market"):
        result[f"{domain}_regime_candidate"] = pd.Series(dtype="object")
        result[f"{domain}_regime"] = pd.Series(dtype="object")
    return result
