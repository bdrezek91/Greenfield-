"""Build the bounded hypothesis queue for one research cycle.

Per the brief: the queue must stay a small, economically-motivated set of
families (ETAP 2 A-E), never an unconstrained indicator/parameter search.
Every cap here comes from `configs/research_protocol.yaml` - nothing is
hardcoded independently of it.

Only family A (time-series momentum/trend) has a runnable strategy
implementation in `src.strategies` today (`momentum`, `trend_following`).
Families B (cross-asset/regime confirmation), C (funding/OI), and D
(portfolio combination) are defined in the protocol and have a recorded
economic rationale, but there is no strategy code implementing them yet -
generating hypotheses for a family with nothing to run would either error
or silently no-op, neither of which is honest. `build_hypothesis_queue`
skips them with an explicit reason instead of pretending they ran. See
docs/AUTONOMOUS_RESEARCH_AUDIT.md's "known limitations" for what
implementing them would take. Family E (microstructure) is disabled in the
protocol itself and is never considered here.
"""

from __future__ import annotations

from dataclasses import dataclass

from src.research.config import ResearchProtocol
from src.research.hypothesis import Hypothesis, make_hypothesis_id

# family id -> (strategy name in src.strategies.registry.ALL_STRATEGIES,
#               parameter grid, one dict of overrides per variant)
_MOMENTUM_TREND_STRATEGIES: dict[str, list[dict]] = {
    "momentum": [
        {"lookback_bars": 10, "threshold": 0.01},
        {"lookback_bars": 20, "threshold": 0.005},
        {"lookback_bars": 20, "threshold": 0.02},
    ],
    "trend_following": [
        {"lookback_bars": 10},
        {"lookback_bars": 20},
    ],
}


@dataclass(frozen=True)
class QueuedHypothesis:
    hypothesis: Hypothesis
    strategy_name: str
    param_grid: tuple[dict, ...]


@dataclass(frozen=True)
class HypothesisQueue:
    queued: tuple[QueuedHypothesis, ...]
    skipped_families: tuple[tuple[str, str], ...]
    """(family_id, reason) for every enabled-in-config family that produced
    no hypotheses this cycle."""


def build_hypothesis_queue(
    protocol: ResearchProtocol, *, start_sequence: int = 1
) -> HypothesisQueue:
    budget = protocol.hypothesis_budget
    queued: list[QueuedHypothesis] = []
    skipped: list[tuple[str, str]] = []
    sequence = start_sequence

    enabled = protocol.enabled_families()
    for family in enabled:
        if family.id != "momentum_trend":
            skipped.append(
                (
                    family.id,
                    "no runnable strategy implementation yet - see "
                    "docs/AUTONOMOUS_RESEARCH_AUDIT.md known limitations",
                )
            )

    momentum_family = next((f for f in enabled if f.id == "momentum_trend"), None)
    if momentum_family is not None:
        for strategy_name, grid in _MOMENTUM_TREND_STRATEGIES.items():
            for symbol in protocol.universe.symbols:
                for timeframe in protocol.universe.timeframes_primary:
                    if len(queued) >= budget.max_new_hypotheses_per_cycle:
                        return HypothesisQueue(
                            queued=tuple(queued), skipped_families=tuple(skipped)
                        )
                    bounded_grid = tuple(grid[: budget.max_variants_per_hypothesis])
                    hyp = Hypothesis(
                        hypothesis_id=make_hypothesis_id(momentum_family.id, sequence),
                        family=momentum_family.id,
                        rationale=(
                            f"{momentum_family.description.strip()} Strategy: {strategy_name}."
                        ),
                        symbols=(symbol,),
                        timeframes=(timeframe,),
                        parameters={
                            "strategy": strategy_name,
                            "param_grid": list(bounded_grid),
                        },
                    )
                    sequence += 1
                    queued.append(
                        QueuedHypothesis(
                            hypothesis=hyp,
                            strategy_name=strategy_name,
                            param_grid=bounded_grid,
                        )
                    )

    return HypothesisQueue(queued=tuple(queued), skipped_families=tuple(skipped))
