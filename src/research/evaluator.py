"""The promotion gate: turns raw OOS evidence into a pass/fail decision
against every threshold in `configs/research_protocol.yaml`.

No single metric here can promote anything on its own - `evaluate_candidate`
requires ALL checks to pass simultaneously, and any missing/incomplete
piece of evidence (funding not applied, mark-to-market not applied,
incomplete data) is itself a hard failure, never a silently-skipped check.
This is the concrete implementation of the brief's rule: "an incomplete/
broken input must stop promotion, not default through."
"""

from __future__ import annotations

from dataclasses import dataclass, field

from src.research.config import PromotionGateConfig


@dataclass(frozen=True)
class CandidateEvidence:
    """Everything the gate needs, already computed by the orchestrator.

    This dataclass intentionally has no defaults for the fields that gate a
    real decision - an orchestrator that "forgot" to compute PBO, for
    example, must fail loudly at construction time, not silently evaluate
    against a placeholder.
    """

    oos_trades: int
    symbols_with_positive_return: int
    aggregate_return_after_adverse_costs: float
    fold_returns: tuple[float, ...]
    trade_returns: tuple[float, ...]
    deflated_sharpe_ratio: float
    probability_of_backtest_overfitting: float
    parameter_stable: bool
    max_drawdown_pct: float
    perturbation_degradation_pct: float
    entry_lag_return_after_one_bar_delay: float
    funding_applied: bool
    mark_to_market_applied: bool
    data_complete: bool
    # Additional stress-test evidence, not a gate (see research_protocol.yaml's
    # costs.severe and docs/AUTONOMOUS_RESEARCH_AUDIT.md M4) - only computed
    # for a candidate that already passed the adverse-cost evaluation, so
    # this legitimately has no value to report for a candidate that failed
    # before reaching that point. Unlike every other field above, this one
    # is allowed a default precisely because it never gates a decision.
    aggregate_return_after_severe_costs: float | None = None


@dataclass(frozen=True)
class CheckResult:
    name: str
    passed: bool
    detail: str


@dataclass(frozen=True)
class PromotionDecision:
    passed: bool
    checks: tuple[CheckResult, ...] = field(default_factory=tuple)

    def failed_checks(self) -> tuple[CheckResult, ...]:
        return tuple(c for c in self.checks if not c.passed)


def _median(values: tuple[float, ...]) -> float:
    if not values:
        return float("nan")
    ordered = sorted(values)
    n = len(ordered)
    mid = n // 2
    if n % 2 == 1:
        return ordered[mid]
    return (ordered[mid - 1] + ordered[mid]) / 2


def _max_share_of_total(values: tuple[float, ...]) -> float:
    """The largest single value's share of the sum of POSITIVE values -
    "does one fold/trade dominate the result" is only meaningful relative
    to the gains, not to a sum that could be near zero or negative.
    """
    positive = [v for v in values if v > 0]
    total_positive = sum(positive)
    if total_positive <= 0:
        return 0.0
    return max(positive) / total_positive


def evaluate_candidate(evidence: CandidateEvidence, gate: PromotionGateConfig) -> PromotionDecision:
    checks: list[CheckResult] = []

    def add(name: str, passed: bool, detail: str) -> None:
        checks.append(CheckResult(name=name, passed=passed, detail=detail))

    add(
        "data_complete",
        evidence.data_complete,
        "backtest input data was validated and complete"
        if evidence.data_complete
        else "data quality check failed or data was incomplete",
    )
    add(
        "funding_applied",
        not gate.requires_funding_applied or evidence.funding_applied,
        "funding cost was charged against every trade"
        if evidence.funding_applied
        else "run had no funding assumptions applied",
    )
    add(
        "mark_to_market_applied",
        not gate.requires_mark_to_market or evidence.mark_to_market_applied,
        "still-open positions were marked to market"
        if evidence.mark_to_market_applied
        else "a still-open position was excluded from the reported metrics",
    )
    add(
        "min_oos_trades",
        evidence.oos_trades >= gate.min_oos_trades,
        f"{evidence.oos_trades} OOS trades (need >= {gate.min_oos_trades})",
    )
    add(
        "min_independent_symbols_positive",
        evidence.symbols_with_positive_return >= gate.min_independent_symbols_positive,
        f"{evidence.symbols_with_positive_return} symbols positive "
        f"(need >= {gate.min_independent_symbols_positive})",
    )
    add(
        "aggregate_oos_return_positive_after_adverse_costs",
        evidence.aggregate_return_after_adverse_costs > 0
        if gate.aggregate_oos_return_positive_after_adverse_costs
        else True,
        f"aggregate OOS return after adverse costs = "
        f"{evidence.aggregate_return_after_adverse_costs:.4f}",
    )
    median_fold = _median(evidence.fold_returns)
    add(
        "median_fold_return_positive",
        (median_fold > 0) if gate.median_fold_return_positive else True,
        f"median fold return = {median_fold:.4f}",
    )
    positive_fraction = (
        sum(1 for r in evidence.fold_returns if r > 0) / len(evidence.fold_returns)
        if evidence.fold_returns
        else 0.0
    )
    add(
        "min_fraction_positive_oos_folds",
        positive_fraction >= gate.min_fraction_positive_oos_folds,
        f"{positive_fraction:.1%} of folds positive "
        f"(need >= {gate.min_fraction_positive_oos_folds:.1%})",
    )
    fold_share = _max_share_of_total(evidence.fold_returns)
    add(
        "max_single_fold_share_of_total_return",
        fold_share <= gate.max_single_fold_share_of_total_return,
        f"largest fold is {fold_share:.1%} of total positive return "
        f"(max {gate.max_single_fold_share_of_total_return:.1%})",
    )
    trade_share = _max_share_of_total(evidence.trade_returns)
    add(
        "max_single_trade_share_of_total_return",
        trade_share <= gate.max_single_trade_share_of_total_return,
        f"largest trade is {trade_share:.1%} of total positive return "
        f"(max {gate.max_single_trade_share_of_total_return:.1%})",
    )
    add(
        "min_deflated_sharpe_ratio",
        evidence.deflated_sharpe_ratio >= gate.min_deflated_sharpe_ratio,
        f"DSR = {evidence.deflated_sharpe_ratio:.3f} (need >= {gate.min_deflated_sharpe_ratio})",
    )
    pbo_ok = (
        evidence.probability_of_backtest_overfitting <= gate.max_probability_of_backtest_overfitting
    )
    add(
        "max_probability_of_backtest_overfitting",
        pbo_ok,
        f"PBO = {evidence.probability_of_backtest_overfitting:.3f} "
        f"(max {gate.max_probability_of_backtest_overfitting})",
    )
    add(
        "require_parameter_stability",
        evidence.parameter_stable if gate.require_parameter_stability else True,
        "parameter region is stable (no isolated spike)"
        if evidence.parameter_stable
        else "best parameters look like an isolated spike, not a stable plateau",
    )
    add(
        "max_drawdown_pct",
        evidence.max_drawdown_pct <= gate.max_drawdown_pct,
        f"max drawdown = {evidence.max_drawdown_pct:.1%} (max {gate.max_drawdown_pct:.1%})",
    )
    add(
        "max_perturbation_degradation_pct",
        evidence.perturbation_degradation_pct <= gate.max_perturbation_degradation_pct,
        f"+/-10-20% parameter perturbation degraded performance by "
        f"{evidence.perturbation_degradation_pct:.1%} "
        f"(max {gate.max_perturbation_degradation_pct:.1%})",
    )
    add(
        "entry_lag_one_bar_must_stay_non_negative",
        evidence.entry_lag_return_after_one_bar_delay >= 0
        if gate.entry_lag_one_bar_must_stay_non_negative
        else True,
        f"return with entry delayed 1 bar = {evidence.entry_lag_return_after_one_bar_delay:.4f}",
    )

    overall = all(c.passed for c in checks)
    return PromotionDecision(passed=overall, checks=tuple(checks))
