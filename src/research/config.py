"""Load and validate configs/research_protocol.yaml.

Every threshold the research worker uses to gate a hypothesis or promote a
candidate lives in that YAML file, never hardcoded in src/research/ - see
the file's own header comment. This module is the single typed entry point
for reading it; nothing else parses the YAML directly.

Percentage scale (Cycle 6 remediation): `paper_promotion.
max_signal_frequency_deviation_pct`, `paper_promotion.min_fill_rate_pct`,
and `retirement.max_paper_drawdown_pct` are 0-100 (e.g. 40.0 means 40%) -
the same scale src.research.degradation's comparisons use - and `_validate`
rejects anything outside [0, 100] for them. `promotion_gate.
max_drawdown_pct`/`max_perturbation_degradation_pct` are a separate,
intentionally 0-1-fraction pair compared directly against walk-forward
equity-curve fractions in src/research/evaluator.py; see the YAML file's
own comment on that field for why it is not on the same scale.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import yaml

DEFAULT_PROTOCOL_PATH = Path(__file__).resolve().parents[2] / "configs" / "research_protocol.yaml"


@dataclass(frozen=True)
class UniverseConfig:
    symbols: tuple[str, ...]
    timeframes_primary: tuple[str, ...]
    timeframes_secondary: tuple[str, ...]
    timeframes_disabled: tuple[str, ...]


@dataclass(frozen=True)
class DataSplitConfig:
    train_days: int
    validation_days: int
    test_days: int
    purge_bars: int
    embargo_bars: int
    max_lookback_days: int | None = None


@dataclass(frozen=True)
class HoldoutConfig:
    enabled: bool
    holdout_id: str
    days: int


@dataclass(frozen=True)
class HypothesisBudgetConfig:
    max_new_hypotheses_per_cycle: int
    max_variants_per_hypothesis: int
    max_cpu_minutes_per_cycle: int
    max_wall_clock_minutes_per_cycle: int


@dataclass(frozen=True)
class HypothesisFamilyConfig:
    id: str
    enabled: bool
    description: str


@dataclass(frozen=True)
class CostScenario:
    fee_multiplier: float
    slippage_multiplier: float
    funding_multiplier: float
    entry_delay_bars: int


@dataclass(frozen=True)
class CostScenarios:
    base: CostScenario
    adverse: CostScenario
    severe: CostScenario


@dataclass(frozen=True)
class PromotionGateConfig:
    min_oos_trades: int
    min_independent_symbols_positive: int
    aggregate_oos_return_positive_after_adverse_costs: bool
    median_fold_return_positive: bool
    min_fraction_positive_oos_folds: float
    max_single_fold_share_of_total_return: float
    max_single_trade_share_of_total_return: float
    min_deflated_sharpe_ratio: float
    max_probability_of_backtest_overfitting: float
    require_parameter_stability: bool
    max_drawdown_pct: float
    max_perturbation_degradation_pct: float
    entry_lag_one_bar_must_stay_non_negative: bool
    requires_funding_applied: bool
    requires_mark_to_market: bool
    requires_complete_data: bool


@dataclass(frozen=True)
class PaperPromotionConfig:
    min_paper_weeks: int
    max_paper_weeks_for_decision: int
    min_paper_trades: int
    max_signal_frequency_deviation_pct: float
    max_fill_slippage_bps: float
    min_fill_rate_pct: float
    no_risk_limit_violations: bool
    requires_human_approval: bool


@dataclass(frozen=True)
class RetirementConfig:
    max_paper_drawdown_pct: float
    consecutive_degraded_reviews_before_retirement: int
    auto_kill_on: tuple[str, ...] = field(default_factory=tuple)


@dataclass(frozen=True)
class ResearchProtocol:
    version: int
    universe: UniverseConfig
    data_split: DataSplitConfig
    holdout: HoldoutConfig
    hypothesis_budget: HypothesisBudgetConfig
    hypothesis_families: tuple[HypothesisFamilyConfig, ...]
    costs: CostScenarios
    promotion_gate: PromotionGateConfig
    paper_promotion: PaperPromotionConfig
    retirement: RetirementConfig

    def enabled_families(self) -> tuple[HypothesisFamilyConfig, ...]:
        return tuple(f for f in self.hypothesis_families if f.enabled)

    def is_symbol_allowed(self, symbol: str) -> bool:
        return symbol in self.universe.symbols

    def is_timeframe_allowed(self, timeframe: str) -> bool:
        return (
            timeframe in self.universe.timeframes_primary
            or timeframe in self.universe.timeframes_secondary
        )


def _cost_scenario(raw: dict) -> CostScenario:
    return CostScenario(
        fee_multiplier=raw["fee_multiplier"],
        slippage_multiplier=raw["slippage_multiplier"],
        funding_multiplier=raw["funding_multiplier"],
        entry_delay_bars=raw["entry_delay_bars"],
    )


def load_research_protocol(path: Path = DEFAULT_PROTOCOL_PATH) -> ResearchProtocol:
    """Parse and validate `path`. Raises on any structural problem - an
    unparsable or incomplete protocol must stop the worker, not run with
    partial/guessed thresholds.
    """
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))

    universe = UniverseConfig(
        symbols=tuple(raw["universe"]["symbols"]),
        timeframes_primary=tuple(raw["universe"]["timeframes_primary"]),
        timeframes_secondary=tuple(raw["universe"]["timeframes_secondary"]),
        timeframes_disabled=tuple(raw["universe"]["timeframes_disabled"]),
    )
    data_split = DataSplitConfig(**raw["data_split"])
    holdout = HoldoutConfig(**raw["holdout"])
    hypothesis_budget = HypothesisBudgetConfig(**raw["hypothesis_budget"])
    families = tuple(
        HypothesisFamilyConfig(id=f["id"], enabled=f["enabled"], description=f["description"])
        for f in raw["hypothesis_families"]
    )
    costs = CostScenarios(
        base=_cost_scenario(raw["costs"]["base"]),
        adverse=_cost_scenario(raw["costs"]["adverse"]),
        severe=_cost_scenario(raw["costs"]["severe"]),
    )
    promotion_gate = PromotionGateConfig(**raw["promotion_gate"])
    paper_promotion = PaperPromotionConfig(**raw["paper_promotion"])
    retirement = RetirementConfig(
        max_paper_drawdown_pct=raw["retirement"]["max_paper_drawdown_pct"],
        consecutive_degraded_reviews_before_retirement=raw["retirement"][
            "consecutive_degraded_reviews_before_retirement"
        ],
        auto_kill_on=tuple(raw["retirement"]["auto_kill_on"]),
    )

    protocol = ResearchProtocol(
        version=raw["version"],
        universe=universe,
        data_split=data_split,
        holdout=holdout,
        hypothesis_budget=hypothesis_budget,
        hypothesis_families=families,
        costs=costs,
        promotion_gate=promotion_gate,
        paper_promotion=paper_promotion,
        retirement=retirement,
    )
    _validate(protocol)
    return protocol


def _validate(protocol: ResearchProtocol) -> None:
    if protocol.hypothesis_budget.max_new_hypotheses_per_cycle <= 0:
        raise ValueError("max_new_hypotheses_per_cycle must be positive")
    if protocol.hypothesis_budget.max_variants_per_hypothesis <= 0:
        raise ValueError("max_variants_per_hypothesis must be positive")
    if not 0.0 <= protocol.promotion_gate.min_fraction_positive_oos_folds <= 1.0:
        raise ValueError("min_fraction_positive_oos_folds must be in [0, 1]")
    if not 0.0 <= protocol.promotion_gate.max_probability_of_backtest_overfitting <= 1.0:
        raise ValueError("max_probability_of_backtest_overfitting must be in [0, 1]")
    if protocol.promotion_gate.min_deflated_sharpe_ratio < 0:
        raise ValueError("min_deflated_sharpe_ratio must be non-negative")
    known_family_ids = {f.id for f in protocol.hypothesis_families}
    if len(known_family_ids) != len(protocol.hypothesis_families):
        raise ValueError("duplicate hypothesis_families id")
    # These three fields are consumed on a 0-100 scale by
    # src.research.degradation (see that module's docstring) - reject
    # anything structurally out of range rather than silently accepting a
    # 0-1 fraction (e.g. 0.40) that would make every degradation check
    # vacuously pass. This does not, and must not, try to guess/rescale an
    # ambiguous value - a genuinely wrong-scale value in [0, 100] (like the
    # historical 0.40/0.90/0.25 bug) is still a config authoring error the
    # loader cannot detect by range alone; only the explicit YAML values
    # are the fix for that.
    _require_pct_0_100(
        protocol.paper_promotion.max_signal_frequency_deviation_pct,
        "paper_promotion.max_signal_frequency_deviation_pct",
    )
    _require_pct_0_100(
        protocol.paper_promotion.min_fill_rate_pct, "paper_promotion.min_fill_rate_pct"
    )
    _require_pct_0_100(
        protocol.retirement.max_paper_drawdown_pct, "retirement.max_paper_drawdown_pct"
    )


def _require_pct_0_100(value: float, field_name: str) -> None:
    if not (isinstance(value, int | float) and not isinstance(value, bool)) or not (
        0.0 <= float(value) <= 100.0
    ):
        raise ValueError(
            f"{field_name} must be a number on a 0-100 percentage scale (got {value!r})"
        )
