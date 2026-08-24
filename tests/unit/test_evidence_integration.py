"""Two independent, real FamilyEvidence producers (Cycles 42-43) feeding
one evaluate_directional_setup call together - the first genuine
multi-family confirmation in this repo's history, not just two isolated
single-family end-to-end tests.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import numpy as np
import pandas as pd

from src.engines.contracts import (
    DataQualityStatus,
    EngineGateState,
    LegSide,
    MarketTarget,
    NumericRange,
    SetupAction,
    SetupLeg,
)
from src.engines.derivatives_evidence import derivatives_family_evidence
from src.engines.directional import (
    DirectionalEngineConfig,
    DirectionalSetupRequest,
    evaluate_directional_setup,
)
from src.engines.order_flow_evidence import order_flow_family_evidence
from src.features.derivatives import derivatives_context_frame

NOW = datetime(2026, 1, 1, 12, tzinfo=UTC)


_AS_OF = pd.Timestamp("2024-01-02T00:00:00Z")


def _derivatives_context(n: int = 25, *, final_return: float = 0.05) -> pd.DataFrame:
    ts = pd.date_range(end=_AS_OF, periods=n, freq="1h", tz="UTC")
    rng = np.random.default_rng(0)
    mark_price = 100.0 + rng.normal(0, 0.05, size=n)
    oi = 1_000.0 + rng.normal(0, 1.0, size=n)
    mark_price[-1] = mark_price[-2] * (1 + final_return)
    oi[-1] = oi[-2] * 1.05  # confirms
    raw = pd.DataFrame(
        {
            "timestamp": ts,
            "max_source_timestamp": ts,
            "mark_price": mark_price,
            "index_price": mark_price,
            "open_interest": oi,
            "funding_rate": 0.0001,
        }
    )
    return derivatives_context_frame(raw, rolling_window=10)


def _trade_flow(n: int = 25, *, final_return: float = 0.05) -> pd.DataFrame:
    ts = pd.date_range(end=_AS_OF, periods=n, freq="1min", tz="UTC")
    rng = np.random.default_rng(1)
    vwap = 100.0 + rng.normal(0, 0.05, size=n)
    delta = rng.normal(0, 1.0, size=n)
    vwap[-1] = vwap[-2] * (1 + final_return)
    delta[-1] = abs(delta[-2]) * (1 if final_return > 0 else -1)  # confirms the same direction
    return pd.DataFrame(
        {
            "timestamp": ts,
            "max_source_timestamp": ts,
            "trade_vwap": vwap,
            "trade_delta": delta,
            "cvd": np.cumsum(delta),
        }
    )


def _gates() -> EngineGateState:
    return EngineGateState(
        kill_switch_active=False,
        operational_healthy=True,
        promotion_eligible=True,
        promotion_state="RESEARCH",
        risk_approved=True,
        risk_reason="approved",
    )


def test_two_independent_confirming_families_approve_a_real_long() -> None:
    derivatives_evidence = derivatives_family_evidence(_derivatives_context(final_return=0.05))
    order_flow_evidence = order_flow_family_evidence(_trade_flow(final_return=0.05))
    assert derivatives_evidence is not None
    assert order_flow_evidence is not None

    cutoff = max(
        derivatives_evidence.max_source_timestamp_utc,
        order_flow_evidence.max_source_timestamp_utc,
    ) + timedelta(seconds=1)
    request = DirectionalSetupRequest(
        target=MarketTarget("BTCUSDT", ("bybit",)),
        decision_timestamp_utc=cutoff,
        data_cutoff_utc=cutoff,
        horizon="1h-4h",
        evidence=(derivatives_evidence, order_flow_evidence),
        regimes=(("trend", "UPTREND"),),
        entry_condition="limit inside validated entry zone",
        invalidation="both families' confirmation reverses",
        stop_logic="hard stop below invalidation",
        expected_gross_value_bps=NumericRange(20, 35, 55),
        expected_cost_bps=NumericRange(2, 4, 8),
        capacity_notional=100_000,
        data_quality_status=DataQualityStatus.PASS,
        model_version="two-family-evidence-v1",
        feature_version="gold-v1",
        gates=_gates(),
    )
    config = DirectionalEngineConfig(minimum_confirming_families=2, family_vote_threshold=0.1)

    decision = evaluate_directional_setup(request, config)

    assert decision.action == SetupAction.LONG
    assert decision.legs == (SetupLeg("BTCUSDT", "bybit", LegSide.BUY),)
    assert len(decision.evidence) == 2


def test_disagreeing_families_wait_instead_of_forcing_a_trade() -> None:
    """One family bullish, one bearish - evaluate_directional_setup's own
    CONFLICTING_INDEPENDENT_FAMILIES rule must produce WAIT, never
    average the disagreement into a weak trade (master plan section
    10.2: "Conflicting high-quality families normally produce WAIT")."""
    derivatives_evidence = derivatives_family_evidence(_derivatives_context(final_return=0.05))
    order_flow_evidence = order_flow_family_evidence(_trade_flow(final_return=-0.05))
    assert derivatives_evidence is not None
    assert order_flow_evidence is not None

    cutoff = max(
        derivatives_evidence.max_source_timestamp_utc,
        order_flow_evidence.max_source_timestamp_utc,
    ) + timedelta(seconds=1)
    request = DirectionalSetupRequest(
        target=MarketTarget("BTCUSDT", ("bybit",)),
        decision_timestamp_utc=cutoff,
        data_cutoff_utc=cutoff,
        horizon="1h-4h",
        evidence=(derivatives_evidence, order_flow_evidence),
        regimes=(("trend", "RANGE"),),
        entry_condition="limit inside validated entry zone",
        invalidation="either family's confirmation reverses",
        stop_logic="hard stop below invalidation",
        expected_gross_value_bps=NumericRange(20, 35, 55),
        expected_cost_bps=NumericRange(2, 4, 8),
        capacity_notional=100_000,
        data_quality_status=DataQualityStatus.PASS,
        model_version="two-family-evidence-v1",
        feature_version="gold-v1",
        gates=_gates(),
    )
    config = DirectionalEngineConfig(minimum_confirming_families=1, family_vote_threshold=0.1)

    decision = evaluate_directional_setup(request, config)

    assert decision.action == SetupAction.WAIT
    assert decision.reason_codes == ("CONFLICTING_INDEPENDENT_FAMILIES",)
