from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from src.engines.contracts import ConfirmationFamily
from src.research.confirmation_independence import (
    ConfirmationIndependenceConfig,
    ConfirmationIndependenceError,
    evaluate_confirmation_independence,
    require_independence_for_promotion,
    write_confirmation_independence_report,
)
from src.research.promotion import PromotionRegistry

AS_OF = datetime(2026, 1, 2, tzinfo=UTC)
CONFIG = ConfirmationIndependenceConfig(1, 100, 0.8, 100, 0.9, 30)


def _frame(a: np.ndarray, b: np.ndarray, regimes: np.ndarray | None = None) -> pd.DataFrame:
    timestamps = pd.date_range("2026-01-01", periods=len(a), freq="min", tz="UTC")
    return pd.DataFrame(
        {
            "timestamp": timestamps,
            "max_source_timestamp": timestamps,
            "regime": regimes if regimes is not None else "NORMAL",
            ConfirmationFamily.ORDER_FLOW.value: a,
            ConfirmationFamily.PRICE_AUCTION.value: b,
        }
    )


def test_independent_families_pass_and_artifact_is_versioned(tmp_path: Path) -> None:
    rng = np.random.default_rng(7)
    report = evaluate_confirmation_independence(
        _frame(rng.normal(size=300), rng.normal(size=300)), as_of_utc=AS_OF, config=CONFIG
    )
    assert report.status == "PASS"
    require_independence_for_promotion(
        report,
        required_families=(ConfirmationFamily.ORDER_FLOW, ConfirmationFamily.PRICE_AUCTION),
    )
    path = tmp_path / "independence.json"
    write_confirmation_independence_report(report, path)
    assert '"schema_version": 1' in path.read_text(encoding="utf-8")


@pytest.mark.parametrize("multiplier", [1.0, -1.0])
def test_strong_positive_or_inverse_dependency_fails(multiplier: float) -> None:
    base = np.linspace(-1, 1, 300)
    report = evaluate_confirmation_independence(
        _frame(base, multiplier * base), as_of_utc=AS_OF, config=CONFIG
    )
    assert report.status == "FAIL"
    assert "FULL_SAMPLE_DEPENDENCE" in report.pairs[0].reasons
    with pytest.raises(ConfirmationIndependenceError, match="not promotion-eligible"):
        require_independence_for_promotion(
            report,
            required_families=(ConfirmationFamily.ORDER_FLOW, ConfirmationFamily.PRICE_AUCTION),
        )


def test_small_sample_is_fail_closed_for_promotion() -> None:
    values = np.arange(20, dtype=float)
    report = evaluate_confirmation_independence(
        _frame(values, values[::-1]), as_of_utc=AS_OF, config=CONFIG
    )
    assert report.status == "INSUFFICIENT_DATA"


def test_constant_family_correlation_is_fail_closed() -> None:
    values = np.ones(300)
    report = evaluate_confirmation_independence(
        _frame(values, values), as_of_utc=AS_OF, config=CONFIG
    )
    assert report.status == "FAIL"
    assert report.pairs[0].reasons == ("NON_FINITE_CORRELATION",)


def test_regime_specific_dependency_is_detected() -> None:
    rng = np.random.default_rng(11)
    first = rng.normal(size=150)
    second = rng.normal(size=150)
    a = np.concatenate([first, second])
    b = np.concatenate([first, rng.normal(size=150)])
    regimes = np.array(["TREND"] * 150 + ["RANGE"] * 150)
    report = evaluate_confirmation_independence(
        _frame(a, b, regimes), as_of_utc=AS_OF, config=CONFIG
    )
    assert report.status == "FAIL"
    assert "REGIME_DEPENDENCE" in report.pairs[0].reasons


def test_future_source_is_rejected() -> None:
    frame = _frame(np.arange(120), np.arange(120)[::-1])
    frame.loc[0, "max_source_timestamp"] = frame.loc[0, "timestamp"] + pd.Timedelta(seconds=1)
    with pytest.raises(ConfirmationIndependenceError, match="future information"):
        evaluate_confirmation_independence(frame, as_of_utc=AS_OF, config=CONFIG)


def test_multi_family_promotion_requires_passing_report(tmp_path: Path) -> None:
    rng = np.random.default_rng(23)
    passing = evaluate_confirmation_independence(
        _frame(rng.normal(size=300), rng.normal(size=300)), as_of_utc=AS_OF, config=CONFIG
    )
    registry = PromotionRegistry(tmp_path / "promotion.json")
    registry.register_research_candidate(
        "multi",
        reason="research complete",
        confirmation_families=(
            ConfirmationFamily.ORDER_FLOW,
            ConfirmationFamily.PRICE_AUCTION,
        ),
    )
    state = registry.promote_multi_family_to_challenger(
        "multi",
        "independence verified",
        independence_report=passing,
        required_families=(ConfirmationFamily.ORDER_FLOW, ConfirmationFamily.PRICE_AUCTION),
    )
    assert state.status == "PAPER_CHALLENGER"


def test_multi_family_candidate_cannot_bypass_independence_gate(tmp_path: Path) -> None:
    registry = PromotionRegistry(tmp_path / "promotion.json")
    registry.register_research_candidate(
        "multi",
        reason="research complete",
        confirmation_families=(
            ConfirmationFamily.ORDER_FLOW,
            ConfirmationFamily.PRICE_AUCTION,
        ),
    )
    with pytest.raises(RuntimeError, match="requires an independence report"):
        registry.promote_to_challenger("multi", "attempted bypass")
