"""src.engines.derivatives_evidence's DERIVATIVES ConfirmationFamily
evidence producer (Cycle 42 - the first FamilyEvidence producer for
src/engines/, previously entirely unreachable since nothing in the repo
produced FamilyEvidence at all, per an autonomous survey before Cycle
37). Tests the scoring rule's own internal logic AND a genuine
end-to-end pass through evaluate_directional_setup.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import numpy as np
import pandas as pd
import pytest

from src.engines.contracts import (
    ConfirmationFamily,
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
from src.features.derivatives import derivatives_context_frame

NOW = datetime(2026, 1, 1, 12, tzinfo=UTC)


def _context(
    n: int = 25,
    *,
    final_return: float = 0.05,
    final_oi_confirms: bool = True,
) -> pd.DataFrame:
    """A quiet, low-variance mark_price/OI series for the first n-1 bars
    (so the rolling z-score has a real, non-degenerate baseline to
    measure the LAST bar's jump against), then one large, deliberate
    move on the final bar."""
    ts = pd.date_range("2024-01-01", periods=n, freq="1h", tz="UTC")
    rng = np.random.default_rng(0)
    mark_price = 100.0 + rng.normal(0, 0.05, size=n)
    oi = 1_000.0 + rng.normal(0, 1.0, size=n)
    mark_price[-1] = mark_price[-2] * (1 + final_return)
    oi[-1] = oi[-2] * (1.05 if final_oi_confirms == (final_return > 0) else 0.95)
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


def test_insufficient_history_returns_none() -> None:
    context = _context(n=10)  # fewer than the default 20-bar zscore window

    assert derivatives_family_evidence(context) is None


def test_empty_frame_returns_none() -> None:
    context = _context(n=25).iloc[:0]

    assert derivatives_family_evidence(context) is None


def test_confirmed_bullish_move_gets_positive_score_and_full_confidence() -> None:
    context = _context(final_return=0.05, final_oi_confirms=True)

    evidence = derivatives_family_evidence(context)

    assert evidence is not None
    assert evidence.family == ConfirmationFamily.DERIVATIVES
    assert evidence.score > 0
    assert evidence.confidence == 1.0
    assert evidence.quality == 1.0
    assert "confirmed" in evidence.rationale


def test_confirmed_bearish_move_gets_negative_score() -> None:
    context = _context(final_return=-0.05, final_oi_confirms=True)

    evidence = derivatives_family_evidence(context)

    assert evidence is not None
    assert evidence.score < 0


def test_contradicted_move_is_fully_zeroed_not_just_dampened() -> None:
    """Price up but OI down (short covering) has real direction but no
    conviction behind it - score must be exactly 0, not a smaller
    positive number, per this module's own "fully zeroed" rule."""
    context = _context(final_return=0.05, final_oi_confirms=False)

    evidence = derivatives_family_evidence(context)

    assert evidence is not None
    assert evidence.score == 0.0
    assert "contradicted" in evidence.rationale


def test_missing_required_columns_raises() -> None:
    bad = pd.DataFrame({"timestamp": [NOW], "max_source_timestamp": [NOW]})
    with pytest.raises(ValueError, match="missing columns"):
        derivatives_family_evidence(bad)


def _gates() -> EngineGateState:
    return EngineGateState(
        kill_switch_active=False,
        operational_healthy=True,
        promotion_eligible=True,
        promotion_state="RESEARCH",
        risk_approved=True,
        risk_reason="approved",
    )


def test_real_evidence_flows_through_evaluate_directional_setup_end_to_end() -> None:
    """The actual payoff: a genuine derivatives_context_frame -> real
    FamilyEvidence -> a real evaluate_directional_setup call produces an
    actionable LONG decision, not just a schema-shaped object. Uses
    minimum_confirming_families=1 since this is deliberately the only
    family wired so far (see this module's own docstring) - a real
    directional decision needs several independent families, not one.
    """
    context = _context(final_return=0.05, final_oi_confirms=True)
    evidence = derivatives_family_evidence(context)
    assert evidence is not None

    request = DirectionalSetupRequest(
        target=MarketTarget("BTCUSDT", ("bybit",)),
        decision_timestamp_utc=evidence.max_source_timestamp_utc + timedelta(seconds=1),
        data_cutoff_utc=evidence.max_source_timestamp_utc + timedelta(seconds=1),
        horizon="1h-4h",
        evidence=(evidence,),
        regimes=(("trend", "UPTREND"),),
        entry_condition="limit inside validated entry zone",
        invalidation="mark return z-score reverts",
        stop_logic="hard stop below invalidation",
        expected_gross_value_bps=NumericRange(20, 35, 55),
        expected_cost_bps=NumericRange(2, 4, 8),
        capacity_notional=100_000,
        data_quality_status=DataQualityStatus.PASS,
        model_version="derivatives-evidence-v1",
        feature_version="gold-v1",
        gates=_gates(),
    )
    config = DirectionalEngineConfig(minimum_confirming_families=1, family_vote_threshold=0.1)

    decision = evaluate_directional_setup(request, config)

    assert decision.action == SetupAction.LONG
    assert decision.legs == (SetupLeg("BTCUSDT", "bybit", LegSide.BUY),)
    assert decision.evidence == (evidence,)
