"""src.engines.order_flow_evidence's ORDER_FLOW ConfirmationFamily
evidence producer (Cycle 43 - second FamilyEvidence producer, parallel
in structure to Cycle 42's derivatives_evidence.py). Uses a directly
hand-shaped trade_flow_frame-column-compatible fixture (same convention
as tests/unit/test_multidomain_regime_bridge.py, Cycle 37) rather than
replaying raw trades through TradeFlowAccumulator - trade_flow_frame's
own correctness is independently covered by tests/unit/test_order_flow.py.
"""

from __future__ import annotations

from datetime import UTC, datetime

import numpy as np
import pandas as pd
import pytest

from src.engines.contracts import ConfirmationFamily
from src.engines.order_flow_evidence import order_flow_family_evidence

NOW = datetime(2026, 1, 1, 12, tzinfo=UTC)


def _trade_flow(
    n: int = 25,
    *,
    final_return: float = 0.05,
    final_delta_confirms: bool = True,
) -> pd.DataFrame:
    """A quiet, low-variance trade_vwap/trade_delta series for the first
    n-1 buckets, then one large, deliberate move on the final bucket -
    same shape as derivatives_evidence's test fixture."""
    ts = pd.date_range("2024-01-01", periods=n, freq="1min", tz="UTC")
    rng = np.random.default_rng(1)
    vwap = 100.0 + rng.normal(0, 0.05, size=n)
    delta = rng.normal(0, 1.0, size=n)
    vwap[-1] = vwap[-2] * (1 + final_return)
    delta[-1] = abs(delta[-2]) * (1 if final_delta_confirms == (final_return > 0) else -1)
    return pd.DataFrame(
        {
            "timestamp": ts,
            "max_source_timestamp": ts,
            "trade_vwap": vwap,
            "trade_delta": delta,
            "cvd": np.cumsum(delta),
        }
    )


def test_insufficient_history_returns_none() -> None:
    trade_flow = _trade_flow(n=10)

    assert order_flow_family_evidence(trade_flow) is None


def test_empty_frame_returns_none() -> None:
    trade_flow = _trade_flow(n=25).iloc[:0]

    assert order_flow_family_evidence(trade_flow) is None


def test_confirmed_bullish_move_gets_positive_score_and_full_confidence() -> None:
    trade_flow = _trade_flow(final_return=0.05, final_delta_confirms=True)

    evidence = order_flow_family_evidence(trade_flow)

    assert evidence is not None
    assert evidence.family == ConfirmationFamily.ORDER_FLOW
    assert evidence.score > 0
    assert evidence.confidence == 1.0
    assert evidence.quality == 1.0
    assert "confirmed" in evidence.rationale


def test_confirmed_bearish_move_gets_negative_score() -> None:
    trade_flow = _trade_flow(final_return=-0.05, final_delta_confirms=True)

    evidence = order_flow_family_evidence(trade_flow)

    assert evidence is not None
    assert evidence.score < 0


def test_contradicted_move_is_fully_zeroed_not_just_dampened() -> None:
    """Price up but aggressor flow net negative (a squeeze without real
    buy-side conviction) has real direction but no conviction behind
    it - score must be exactly 0."""
    trade_flow = _trade_flow(final_return=0.05, final_delta_confirms=False)

    evidence = order_flow_family_evidence(trade_flow)

    assert evidence is not None
    assert evidence.score == 0.0
    assert "contradicted" in evidence.rationale


def test_missing_required_columns_raises() -> None:
    bad = pd.DataFrame({"timestamp": [NOW], "max_source_timestamp": [NOW]})
    with pytest.raises(ValueError, match="missing columns"):
        order_flow_family_evidence(bad)


def test_evidence_max_source_timestamp_matches_the_latest_bucket() -> None:
    trade_flow = _trade_flow(final_return=0.05, final_delta_confirms=True)

    evidence = order_flow_family_evidence(trade_flow)

    assert evidence is not None
    expected = trade_flow["max_source_timestamp"].iloc[-1].to_pydatetime()
    assert evidence.max_source_timestamp_utc == expected
