from __future__ import annotations

from src.research.config import load_research_protocol
from src.research.evaluator import CandidateEvidence, evaluate_candidate

_GATE = load_research_protocol().promotion_gate


def _passing_evidence(**overrides) -> CandidateEvidence:
    base = dict(
        oos_trades=50,
        symbols_with_positive_return=2,
        aggregate_return_after_adverse_costs=0.05,
        fold_returns=(0.01, 0.02, -0.005, 0.015, 0.008),
        trade_returns=tuple([0.001] * 40 + [0.002] * 10),
        deflated_sharpe_ratio=1.2,
        probability_of_backtest_overfitting=0.1,
        parameter_stable=True,
        max_drawdown_pct=0.15,
        perturbation_degradation_pct=0.1,
        entry_lag_return_after_one_bar_delay=0.01,
        funding_applied=True,
        mark_to_market_applied=True,
        data_complete=True,
    )
    base.update(overrides)
    return CandidateEvidence(**base)


def test_fully_passing_evidence_passes() -> None:
    decision = evaluate_candidate(_passing_evidence(), _GATE)
    assert decision.passed is True
    assert decision.failed_checks() == ()


def test_missing_funding_blocks_promotion() -> None:
    decision = evaluate_candidate(_passing_evidence(funding_applied=False), _GATE)
    assert decision.passed is False
    assert any(c.name == "funding_applied" for c in decision.failed_checks())


def test_missing_mark_to_market_blocks_promotion() -> None:
    decision = evaluate_candidate(_passing_evidence(mark_to_market_applied=False), _GATE)
    assert decision.passed is False
    assert any(c.name == "mark_to_market_applied" for c in decision.failed_checks())


def test_incomplete_data_blocks_promotion_even_if_everything_else_passes() -> None:
    decision = evaluate_candidate(_passing_evidence(data_complete=False), _GATE)
    assert decision.passed is False
    assert any(c.name == "data_complete" for c in decision.failed_checks())


def test_too_few_trades_blocks_promotion() -> None:
    decision = evaluate_candidate(_passing_evidence(oos_trades=5), _GATE)
    assert decision.passed is False
    assert any(c.name == "min_oos_trades" for c in decision.failed_checks())


def test_single_symbol_positive_blocks_promotion() -> None:
    decision = evaluate_candidate(_passing_evidence(symbols_with_positive_return=1), _GATE)
    assert decision.passed is False


def test_low_dsr_blocks_promotion() -> None:
    decision = evaluate_candidate(_passing_evidence(deflated_sharpe_ratio=0.1), _GATE)
    assert decision.passed is False
    assert any(c.name == "min_deflated_sharpe_ratio" for c in decision.failed_checks())


def test_high_pbo_blocks_promotion() -> None:
    decision = evaluate_candidate(
        _passing_evidence(probability_of_backtest_overfitting=0.9), _GATE
    )
    assert decision.passed is False
    assert any(
        c.name == "max_probability_of_backtest_overfitting" for c in decision.failed_checks()
    )


def test_one_dominant_fold_blocks_promotion() -> None:
    decision = evaluate_candidate(
        _passing_evidence(fold_returns=(0.5, 0.001, 0.001, 0.001, -0.01)), _GATE
    )
    assert decision.passed is False
    assert any(
        c.name == "max_single_fold_share_of_total_return" for c in decision.failed_checks()
    )


def test_unstable_parameters_blocks_promotion() -> None:
    decision = evaluate_candidate(_passing_evidence(parameter_stable=False), _GATE)
    assert decision.passed is False


def test_negative_return_after_entry_lag_blocks_promotion() -> None:
    decision = evaluate_candidate(
        _passing_evidence(entry_lag_return_after_one_bar_delay=-0.001), _GATE
    )
    assert decision.passed is False
    assert any(
        c.name == "entry_lag_one_bar_must_stay_non_negative" for c in decision.failed_checks()
    )


def test_excessive_drawdown_blocks_promotion() -> None:
    decision = evaluate_candidate(_passing_evidence(max_drawdown_pct=0.9), _GATE)
    assert decision.passed is False


def test_no_candidate_is_a_valid_outcome_not_an_error() -> None:
    """A cycle where nothing passes must produce a clean, structured
    failure (NO_CANDIDATE), never an exception."""
    decision = evaluate_candidate(_passing_evidence(oos_trades=0, deflated_sharpe_ratio=0.0), _GATE)
    assert isinstance(decision.passed, bool)
    assert decision.passed is False
