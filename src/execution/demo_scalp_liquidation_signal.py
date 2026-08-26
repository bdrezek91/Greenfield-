"""Liquidation-cascade fade signal for the "druga proba scalpingu" candidate.

Research rationale (see docs/CLAUDE_CODE_CONTINUATION.md "druga proba
scalpingu" entry for the full writeup): forced liquidations on a leveraged
perpetual market are a mechanical, non-discretionary source of order flow -
unlike a lagging technical indicator, a large liquidation notional is direct
evidence that a specific set of participants was just forced to trade, often
overshooting fair value. The hypothesis this module encodes is a fade
(mean-reversion) of that overshoot: a burst of forced SELL liquidation
(longs being closed) is a tentative LONG signal, and a burst of forced BUY
liquidation (shorts being closed) is a tentative SHORT signal.

This hypothesis has NOT been backtested on this system's own historical
data. It is deployed as a second, clearly-labelled experimental candidate
(EXPERIMENTAL_DEMO_SCALP_V2_LIQUIDATION_FADE, still
DEMO_EXPERIMENT_ONLY_NOT_PROMOTED) specifically to gather the evidence the
first candidate never collected before being run continuously.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from enum import StrEnum

from src.engines.contracts import SetupAction


class LiquidatedSide(StrEnum):
    """The side of the position that was forcibly closed."""

    LONGS = "LONGS"
    SHORTS = "SHORTS"


@dataclass(frozen=True, slots=True)
class LiquidationEvent:
    timestamp_utc: datetime
    side: LiquidatedSide
    price: float
    size: float

    def __post_init__(self) -> None:
        _utc(self.timestamp_utc, "liquidation event timestamp")
        if (
            not math.isfinite(self.price)
            or self.price <= 0
            or not math.isfinite(self.size)
            or self.size <= 0
        ):
            raise ValueError("invalid liquidation event")

    @property
    def notional(self) -> float:
        return self.price * self.size


@dataclass(frozen=True, slots=True)
class LiquidationCascadeSignal:
    detected: bool
    direction: SetupAction
    liquidated_side: LiquidatedSide | None
    window_notional: float
    reference_notional: float
    notional_ratio: float


@dataclass(frozen=True, slots=True)
class LiquidationCascadeConfig:
    lookback_seconds: float = 180.0
    reference_window_seconds: float = 1_800.0
    minimum_notional_ratio: float = 3.0
    minimum_window_notional: float = 50_000.0

    def __post_init__(self) -> None:
        if not math.isfinite(self.lookback_seconds) or self.lookback_seconds <= 0:
            raise ValueError("liquidation lookback window must be positive")
        if (
            not math.isfinite(self.reference_window_seconds)
            or self.reference_window_seconds <= self.lookback_seconds
        ):
            raise ValueError("reference window must be longer than the lookback window")
        if not math.isfinite(self.minimum_notional_ratio) or self.minimum_notional_ratio <= 1:
            raise ValueError("minimum notional ratio must exceed 1")
        if (
            not math.isfinite(self.minimum_window_notional)
            or self.minimum_window_notional <= 0
        ):
            raise ValueError("minimum window notional must be positive")


def detect_liquidation_cascade(
    events: tuple[LiquidationEvent, ...],
    *,
    observed_at_utc: datetime,
    config: LiquidationCascadeConfig | None = None,
) -> LiquidationCascadeSignal:
    """Fail closed to a no-signal result on anything short of a clear cascade.

    `events` must cover at least `reference_window_seconds` of history so the
    lookback window's notional can be compared against a same-length-normalised
    baseline - a caller supplying only the lookback window itself would make
    every burst look infinitely large relative to an empty reference.
    """
    config = config or LiquidationCascadeConfig()
    observed = _utc(observed_at_utc, "liquidation cascade observation timestamp")
    if any(event.timestamp_utc > observed for event in events):
        raise ValueError("liquidation cascade evidence cannot follow observation time")

    lookback_start = observed.timestamp() - config.lookback_seconds
    reference_start = observed.timestamp() - config.reference_window_seconds
    window_events = [e for e in events if e.timestamp_utc.timestamp() >= lookback_start]
    reference_events = [e for e in events if e.timestamp_utc.timestamp() >= reference_start]

    window_notional = sum(event.notional for event in window_events)
    reference_notional = sum(event.notional for event in reference_events)
    # Normalise the reference bucket to the lookback window's own length so a
    # short, sparse reference history doesn't produce a spuriously low
    # baseline (and therefore a spuriously high ratio).
    normalised_reference = reference_notional * (
        config.lookback_seconds / config.reference_window_seconds
    )
    baseline = max(normalised_reference, 1.0)
    ratio = window_notional / baseline

    no_signal = LiquidationCascadeSignal(
        detected=False,
        direction=SetupAction.WAIT,
        liquidated_side=None,
        window_notional=window_notional,
        reference_notional=reference_notional,
        notional_ratio=ratio,
    )
    if window_notional < config.minimum_window_notional or ratio < config.minimum_notional_ratio:
        return no_signal

    long_liquidated = sum(e.notional for e in window_events if e.side is LiquidatedSide.LONGS)
    short_liquidated = sum(e.notional for e in window_events if e.side is LiquidatedSide.SHORTS)
    if long_liquidated == short_liquidated:
        # No clear dominant side within the window - not a directional cascade.
        return no_signal
    dominant = LiquidatedSide.LONGS if long_liquidated > short_liquidated else LiquidatedSide.SHORTS
    # Fade hypothesis: forced closure of longs (mechanical sell pressure) is
    # a tentative LONG (buy the flush); forced closure of shorts is SHORT.
    direction = SetupAction.LONG if dominant is LiquidatedSide.LONGS else SetupAction.SHORT
    return LiquidationCascadeSignal(
        detected=True,
        direction=direction,
        liquidated_side=dominant,
        window_notional=window_notional,
        reference_notional=reference_notional,
        notional_ratio=ratio,
    )


@dataclass(frozen=True, slots=True)
class FundingRegimeConfig:
    extreme_funding_rate: Decimal = Decimal("0.0005")

    def __post_init__(self) -> None:
        if not self.extreme_funding_rate.is_finite() or self.extreme_funding_rate <= 0:
            raise ValueError("extreme funding rate threshold must be positive")


def funding_regime_allows(
    direction: SetupAction, funding_rate: Decimal, *, config: FundingRegimeConfig | None = None
) -> bool:
    """Veto a cascade-fade direction that fights an already-crowded regime.

    Extreme positive funding means longs are paying heavily to stay long -
    the crowd is already positioned long, so a fresh LONG entry (even one
    fading a short-liquidation squeeze) is adding to the crowded side.
    Extreme negative funding is the mirror case for SHORT. A neutral
    funding regime allows either direction through unfiltered.
    """
    config = config or FundingRegimeConfig()
    if not funding_rate.is_finite():
        raise ValueError("funding rate must be finite")
    if direction not in {SetupAction.LONG, SetupAction.SHORT}:
        return False
    if funding_rate >= config.extreme_funding_rate and direction is SetupAction.LONG:
        return False
    if funding_rate <= -config.extreme_funding_rate and direction is SetupAction.SHORT:
        return False
    return True


def _utc(value: datetime, name: str) -> datetime:
    if value.tzinfo is None:
        raise ValueError(f"{name} must be timezone-aware")
    return value.astimezone(UTC)
