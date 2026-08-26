from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from src.engines.contracts import SetupAction
from src.execution.demo_scalp_liquidation_signal import (
    FundingRegimeConfig,
    LiquidatedSide,
    LiquidationCascadeConfig,
    LiquidationEvent,
    detect_liquidation_cascade,
    funding_regime_allows,
)

NOW = datetime(2026, 8, 26, 12, 0, tzinfo=UTC)


def _event(seconds_ago: float, side: LiquidatedSide, *, price: float = 80_000.0, size: float = 1.0):
    return LiquidationEvent(
        timestamp_utc=NOW - timedelta(seconds=seconds_ago), side=side, price=price, size=size
    )


def test_no_signal_below_minimum_notional() -> None:
    config = LiquidationCascadeConfig(minimum_window_notional=1_000_000.0)
    events = (_event(10, LiquidatedSide.LONGS, size=0.1),)
    result = detect_liquidation_cascade(events, observed_at_utc=NOW, config=config)
    assert not result.detected
    assert result.direction is SetupAction.WAIT


def test_no_signal_when_ratio_below_threshold() -> None:
    config = LiquidationCascadeConfig(minimum_notional_ratio=3.0, minimum_window_notional=1.0)
    # Same average notional in window and reference -> ratio ~= 1, below threshold.
    events = tuple(_event(seconds, LiquidatedSide.LONGS) for seconds in range(0, 1800, 60))
    result = detect_liquidation_cascade(events, observed_at_utc=NOW, config=config)
    assert not result.detected


def test_detects_long_liquidation_cascade_and_fades_to_long() -> None:
    config = LiquidationCascadeConfig(
        lookback_seconds=180,
        reference_window_seconds=1_800,
        minimum_notional_ratio=3.0,
        minimum_window_notional=1.0,
    )
    # A quiet reference history, then a burst of forced long-closing sells
    # right before the observation time.
    quiet = tuple(
        _event(seconds, LiquidatedSide.LONGS, size=0.01) for seconds in range(300, 1800, 300)
    )
    burst = tuple(_event(seconds, LiquidatedSide.LONGS, size=5.0) for seconds in (10, 30, 60))
    result = detect_liquidation_cascade(quiet + burst, observed_at_utc=NOW, config=config)

    assert result.detected
    assert result.direction is SetupAction.LONG
    assert result.liquidated_side is LiquidatedSide.LONGS


def test_detects_short_liquidation_cascade_and_fades_to_short() -> None:
    config = LiquidationCascadeConfig(
        lookback_seconds=180,
        reference_window_seconds=1_800,
        minimum_notional_ratio=3.0,
        minimum_window_notional=1.0,
    )
    quiet = tuple(
        _event(seconds, LiquidatedSide.SHORTS, size=0.01) for seconds in range(300, 1800, 300)
    )
    burst = tuple(_event(seconds, LiquidatedSide.SHORTS, size=5.0) for seconds in (10, 30, 60))
    result = detect_liquidation_cascade(quiet + burst, observed_at_utc=NOW, config=config)

    assert result.detected
    assert result.direction is SetupAction.SHORT


def test_mixed_evenly_split_liquidations_are_not_directional() -> None:
    config = LiquidationCascadeConfig(minimum_notional_ratio=3.0, minimum_window_notional=1.0)
    events = (
        _event(10, LiquidatedSide.LONGS, size=5.0),
        _event(20, LiquidatedSide.SHORTS, size=5.0),
    )
    result = detect_liquidation_cascade(events, observed_at_utc=NOW, config=config)
    assert not result.detected


def test_future_event_is_rejected() -> None:
    events = (_event(-10, LiquidatedSide.LONGS),)
    with pytest.raises(ValueError, match="cannot follow"):
        detect_liquidation_cascade(events, observed_at_utc=NOW)


def test_funding_regime_vetoes_long_when_funding_extremely_positive() -> None:
    config = FundingRegimeConfig(extreme_funding_rate=Decimal("0.0005"))
    assert not funding_regime_allows(SetupAction.LONG, Decimal("0.001"), config=config)
    assert funding_regime_allows(SetupAction.SHORT, Decimal("0.001"), config=config)


def test_funding_regime_vetoes_short_when_funding_extremely_negative() -> None:
    config = FundingRegimeConfig(extreme_funding_rate=Decimal("0.0005"))
    assert not funding_regime_allows(SetupAction.SHORT, Decimal("-0.001"), config=config)
    assert funding_regime_allows(SetupAction.LONG, Decimal("-0.001"), config=config)


def test_funding_regime_allows_both_directions_when_neutral() -> None:
    config = FundingRegimeConfig(extreme_funding_rate=Decimal("0.0005"))
    assert funding_regime_allows(SetupAction.LONG, Decimal("0.0001"), config=config)
    assert funding_regime_allows(SetupAction.SHORT, Decimal("-0.0001"), config=config)
