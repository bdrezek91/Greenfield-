"""Causal Bybit opportunity scans for the autonomous Demo PAPER path.

The scanner deliberately stops before order submission.  It turns one
immutable public-market snapshot into the existing Directional Engine input,
keeps ATAS-like auction/order-flow evidence in separate confirmation families,
and uses the original Market-Cipher-like momentum/money-flow implementation as
a veto only.  A momentum veto therefore cannot be counted as another
independent confirmation.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from enum import StrEnum

import numpy as np
import pandas as pd

from src.engines.contracts import (
    DataQualityStatus,
    EngineGateState,
    FamilyEvidence,
    MarketTarget,
    NumericRange,
    SetupAction,
    SetupDecision,
)
from src.engines.derivatives_evidence import derivatives_family_evidence
from src.engines.directional import (
    DirectionalEngineConfig,
    DirectionalSetupRequest,
    evaluate_directional_setup,
)
from src.engines.order_flow_evidence import order_flow_family_evidence
from src.engines.price_auction_evidence import price_auction_family_evidence
from src.features.auction import volume_profile
from src.features.derivatives import derivatives_context_frame
from src.features.momentum_flow import momentum_money_flow_frame


class MomentumVeto(StrEnum):
    LONG = "LONG"
    SHORT = "SHORT"
    WAIT = "WAIT"


@dataclass(frozen=True, slots=True)
class PublicTrade:
    trade_id: str
    timestamp_utc: datetime
    side: str
    price: float
    size: float

    def __post_init__(self) -> None:
        _utc(self.timestamp_utc, "public trade timestamp")
        if (
            not self.trade_id.strip()
            or self.side not in {"buy", "sell"}
            or not math.isfinite(self.price)
            or self.price <= 0
            or not math.isfinite(self.size)
            or self.size <= 0
        ):
            raise ValueError("invalid public trade")


@dataclass(frozen=True, slots=True)
class BybitOpportunitySnapshot:
    symbol: str
    observed_at_utc: datetime
    candles: pd.DataFrame
    trades: tuple[PublicTrade, ...]
    derivatives: pd.DataFrame
    price_tick: float

    def __post_init__(self) -> None:
        _utc(self.observed_at_utc, "opportunity observation timestamp")
        if not self.symbol or self.symbol != self.symbol.upper():
            raise ValueError("opportunity symbol must be uppercase")
        if not math.isfinite(self.price_tick) or self.price_tick <= 0:
            raise ValueError("opportunity price tick must be positive")


@dataclass(frozen=True, slots=True)
class PromotedEdgeProfile:
    candidate_id: str
    promotion_state: str
    expected_gross_value_bps: NumericRange
    expected_cost_bps: NumericRange
    capacity_notional: float

    def __post_init__(self) -> None:
        if not self.candidate_id.strip() or not self.promotion_state.strip():
            raise ValueError("edge profile requires candidate and promotion state")
        if not math.isfinite(self.capacity_notional) or self.capacity_notional < 0:
            raise ValueError("edge capacity must be finite and non-negative")

    @property
    def paper_eligible(self) -> bool:
        return self.promotion_state in {"PAPER_CHALLENGER", "PAPER_CHAMPION"}


@dataclass(frozen=True, slots=True)
class DemoOpportunityScannerConfig:
    minimum_candles: int = 50
    minimum_trades: int = 300
    order_flow_buckets: int = 25
    volume_profile_trade_count: int = 750
    maximum_data_age_seconds: float = 360.0
    family_vote_threshold: float = 0.25

    def __post_init__(self) -> None:
        if (
            self.minimum_candles < 30
            or self.minimum_trades < 100
            or self.order_flow_buckets < 20
            or self.volume_profile_trade_count < 100
            or not math.isfinite(self.maximum_data_age_seconds)
            or self.maximum_data_age_seconds <= 0
            or not 0 < self.family_vote_threshold <= 1
        ):
            raise ValueError("invalid Demo opportunity scanner configuration")


@dataclass(frozen=True, slots=True)
class DemoOpportunityScan:
    symbol: str
    candidate_id: str
    decision: SetupDecision
    momentum_veto: MomentumVeto
    evidence: tuple[FamilyEvidence, ...]


class DemoOpportunityScanner:
    """Build a fail-closed directional decision from public market evidence."""

    def __init__(self, config: DemoOpportunityScannerConfig | None = None) -> None:
        self.config = config or DemoOpportunityScannerConfig()

    def scan(
        self,
        snapshot: BybitOpportunitySnapshot,
        *,
        edge: PromotedEdgeProfile,
        operational_healthy: bool = True,
        kill_switch_active: bool = False,
    ) -> DemoOpportunityScan:
        observed = _utc(snapshot.observed_at_utc, "opportunity observation timestamp")
        candles = _validate_candles(snapshot.candles, minimum=self.config.minimum_candles)
        trades = _validate_trades(snapshot.trades, minimum=self.config.minimum_trades)
        evidence = tuple(
            item
            for item in (
                _price_auction_evidence(
                    trades,
                    price_tick=snapshot.price_tick,
                    maximum_trades=self.config.volume_profile_trade_count,
                ),
                order_flow_family_evidence(
                    _event_count_trade_flow(trades, buckets=self.config.order_flow_buckets),
                    vwap_return_zscore_window=20,
                ),
                derivatives_family_evidence(
                    derivatives_context_frame(snapshot.derivatives, rolling_window=20),
                    mark_return_zscore_window=20,
                ),
            )
            if item is not None
        )
        cutoff = max((item.max_source_timestamp_utc for item in evidence), default=observed)
        if cutoff > observed:
            raise ValueError("opportunity evidence cannot follow observation time")
        momentum = _momentum_veto(candles)
        risk_approved = momentum is not MomentumVeto.WAIT
        request = DirectionalSetupRequest(
            target=MarketTarget(snapshot.symbol, ("bybit",)),
            decision_timestamp_utc=observed,
            data_cutoff_utc=observed,
            horizon="15m-1h",
            evidence=evidence,
            regimes=(("runtime", "UNCLASSIFIED"),),
            entry_condition="three independent families align and momentum veto agrees",
            invalidation="family consensus or momentum veto reverses",
            stop_logic="durable reduce-only stop/time exit under Demo risk limits",
            expected_gross_value_bps=edge.expected_gross_value_bps,
            expected_cost_bps=edge.expected_cost_bps,
            capacity_notional=edge.capacity_notional,
            data_quality_status=(
                DataQualityStatus.PASS if len(evidence) == 3 else DataQualityStatus.FAIL
            ),
            model_version=edge.candidate_id,
            feature_version="bybit-public-opportunity-v1",
            gates=EngineGateState(
                kill_switch_active=kill_switch_active,
                operational_healthy=operational_healthy,
                promotion_eligible=edge.paper_eligible,
                promotion_state=edge.promotion_state,
                risk_approved=risk_approved,
                risk_reason=(
                    "momentum filter directional" if risk_approved else "momentum filter neutral"
                ),
            ),
        )
        directional_config = DirectionalEngineConfig(
            minimum_confirming_families=3,
            family_vote_threshold=self.config.family_vote_threshold,
            maximum_data_age_seconds=self.config.maximum_data_age_seconds,
        )
        decision = evaluate_directional_setup(request, directional_config)
        if decision.action is SetupAction.LONG and momentum is not MomentumVeto.LONG:
            decision = evaluate_directional_setup(
                replace(
                    request,
                    gates=replace(
                        request.gates,
                        risk_approved=False,
                        risk_reason="momentum veto rejects LONG",
                    ),
                ),
                directional_config,
            )
        elif decision.action is SetupAction.SHORT and momentum is not MomentumVeto.SHORT:
            decision = evaluate_directional_setup(
                replace(
                    request,
                    gates=replace(
                        request.gates,
                        risk_approved=False,
                        risk_reason="momentum veto rejects SHORT",
                    ),
                ),
                directional_config,
            )
        return DemoOpportunityScan(
            symbol=snapshot.symbol,
            candidate_id=edge.candidate_id,
            decision=decision,
            momentum_veto=momentum,
            evidence=evidence,
        )


def _validate_candles(frame: pd.DataFrame, *, minimum: int) -> pd.DataFrame:
    required = {"timestamp", "max_source_timestamp", "open", "high", "low", "close", "volume"}
    missing = sorted(required - set(frame.columns))
    if missing:
        raise ValueError(f"opportunity candles missing columns: {missing}")
    value = frame.sort_values("timestamp").reset_index(drop=True).copy()
    if len(value) < minimum:
        raise ValueError("insufficient candles for opportunity scan")
    value["timestamp"] = pd.to_datetime(value["timestamp"], utc=True)
    value["max_source_timestamp"] = pd.to_datetime(value["max_source_timestamp"], utc=True)
    if (value["max_source_timestamp"] > value["timestamp"]).any():
        raise ValueError("candle source timestamp follows feature timestamp")
    numeric = value[["open", "high", "low", "close", "volume"]].astype(float)
    invalid_price = (numeric[["open", "high", "low", "close"]] <= 0).any().any()
    if (
        not np.isfinite(numeric.to_numpy()).all()
        or invalid_price
        or (numeric["volume"] < 0).any()
    ):
        raise ValueError("invalid opportunity candle values")
    return value


def _validate_trades(
    trades: tuple[PublicTrade, ...], *, minimum: int
) -> tuple[PublicTrade, ...]:
    ordered = tuple(sorted(trades, key=lambda item: (item.timestamp_utc, item.trade_id)))
    if len(ordered) < minimum:
        raise ValueError("insufficient public trades for opportunity scan")
    if len({item.trade_id for item in ordered}) != len(ordered):
        raise ValueError("duplicate public trade ids")
    return ordered


def _event_count_trade_flow(
    trades: tuple[PublicTrade, ...], *, buckets: int
) -> pd.DataFrame:
    if len(trades) < buckets:
        return pd.DataFrame()
    groups = np.array_split(np.arange(len(trades)), buckets)
    rows = []
    for indexes in groups:
        values = [trades[int(index)] for index in indexes]
        total_size = sum(item.size for item in values)
        buy = sum(item.size for item in values if item.side == "buy")
        sell = total_size - buy
        source = max(item.timestamp_utc for item in values)
        rows.append(
            {
                "timestamp": pd.Timestamp(source),
                "max_source_timestamp": pd.Timestamp(source),
                "trade_vwap": sum(item.price * item.size for item in values) / total_size,
                "trade_delta": buy - sell,
            }
        )
    return pd.DataFrame(rows)


def _price_auction_evidence(
    trades: tuple[PublicTrade, ...], *, price_tick: float, maximum_trades: int
) -> FamilyEvidence | None:
    selected = trades[-maximum_trades:]
    levels: dict[float, float] = {}
    for item in selected:
        level = round(item.price / price_tick) * price_tick
        levels[level] = levels.get(level, 0.0) + item.size
    footprint = pd.DataFrame(
        {"price_level": list(levels), "total_volume": list(levels.values())}
    )
    profile = volume_profile(footprint)
    latest = selected[-1]
    return price_auction_family_evidence(
        pd.DataFrame(
            {
                "timestamp": [pd.Timestamp(latest.timestamp_utc)],
                "poc": [profile.poc],
                "vah": [profile.vah],
                "val": [profile.val],
                "close": [latest.price],
            }
        )
    )


def _momentum_veto(candles: pd.DataFrame) -> MomentumVeto:
    frame = momentum_money_flow_frame(candles)
    if frame.empty:
        return MomentumVeto.WAIT
    latest = frame.iloc[-1]
    wave = float(latest["momentum_wave"])
    signal = float(latest["momentum_signal"])
    money_flow = float(latest["money_flow"])
    rsi = float(latest["rsi"])
    if wave > signal and money_flow > 0 and 50 <= rsi < 75:
        return MomentumVeto.LONG
    if wave < signal and money_flow < 0 and 25 < rsi <= 50:
        return MomentumVeto.SHORT
    return MomentumVeto.WAIT


def _utc(value: datetime, name: str) -> datetime:
    if value.tzinfo is None:
        raise ValueError(f"{name} must be timezone-aware")
    return value.astimezone(UTC)
