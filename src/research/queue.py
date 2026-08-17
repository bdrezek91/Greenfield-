"""Build the bounded hypothesis queue for one research cycle.

Per the brief: the queue must stay a small, economically-motivated set of
families (ETAP 2 A-E), never an unconstrained indicator/parameter search.
Every cap here comes from `configs/research_protocol.yaml` - nothing is
hardcoded independently of it.

Family A (time-series momentum/trend: `momentum`, `trend_following`),
family B (cross-asset/regime confirmation: `cross_asset_momentum`, BTC as
a trend filter for other symbols), and family C (funding/OI contrarian:
`funding_contrarian`, extreme funding confirmed by rising open interest)
have runnable strategy implementations. Family D (portfolio combination)
is defined in the protocol and has a recorded economic rationale, but
there is no strategy code implementing it yet - generating hypotheses for
a family with nothing to run would either error or silently no-op,
neither of which is honest. `build_hypothesis_queue` skips it with an
explicit reason instead of pretending it ran. It is blocked on there being
at least one individually-positive strategy to combine in the first place
(everything from families A-C has been NO_CANDIDATE so far), not just on
missing code. See docs/AUTONOMOUS_RESEARCH_AUDIT.md's "known limitations"
for detail. Family E (microstructure) is disabled in the protocol itself
and is never considered here.
"""

from __future__ import annotations

from dataclasses import dataclass

from src.research.config import ResearchProtocol
from src.research.hypothesis import Hypothesis, make_hypothesis_id

# ATR-based exit (src.strategies.base's use_atr_exit) was tried here for
# one cycle (2026-08-17, atr_period=14, atr_exit_multiple=2.0) on the
# theory that a fixed-bar hold disconnected from price movement was
# contributing to the consistently poor results families A-C had shown.
# Measured, not assumed: trade counts on 4h roughly doubled (e.g. momentum
# BTCUSDT 142->305 trades) because a 2x-ATR stop is tight enough to get
# whipsawed by ordinary noise on these assets/timeframes, and every
# resulting metric got WORSE, not better - DSR fell further toward zero,
# funding_contrarian's already-thin daily OOS trade counts collapsed
# further (13->4, nowhere near min_oos_trades=30). The extra turnover's
# transaction costs dominated. Reverted to the plain fixed-bar hold below;
# use_atr_exit stays available in src/strategies/base.py for a future,
# differently-parameterized test, but is not applied by default now that
# the one measurement there is shows it makes things worse, not better -
# see docs/AUTONOMOUS_RESEARCH_AUDIT.md.

# family id -> (strategy name in src.strategies.registry.RESEARCH_STRATEGIES,
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

# BTC is the reference/regime instrument for family B, per its rationale in
# configs/research_protocol.yaml - never a target itself (that would be
# "BTC confirmed by BTC's own regime", not a cross-asset hypothesis).
_CROSS_ASSET_REFERENCE_SYMBOL = "BTCUSDT"
_CROSS_ASSET_STRATEGIES: dict[str, list[dict]] = {
    "cross_asset_momentum": [
        {"lookback_bars": 10, "threshold": 0.01},
        {"lookback_bars": 20, "threshold": 0.005},
    ],
}

_FUNDING_OI_STRATEGIES: dict[str, list[dict]] = {
    "funding_contrarian": [
        {"funding_zscore_lookback": 30, "funding_zscore_threshold": 1.5, "oi_confirmation_bars": 5},
        {
            "funding_zscore_lookback": 60,
            "funding_zscore_threshold": 2.0,
            "oi_confirmation_bars": 10,
        },
    ],
}


@dataclass(frozen=True)
class QueuedHypothesis:
    hypothesis: Hypothesis
    strategy_name: str
    param_grid: tuple[dict, ...]
    reference_symbol: str | None = None
    """Set for family B (cross-asset) hypotheses - the second symbol whose
    data must also be loaded and validated alongside the target."""


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
    enabled_by_id = {f.id: f for f in enabled}

    for family in enabled:
        if family.id not in ("momentum_trend", "cross_asset_regime", "funding_oi"):
            skipped.append(
                (
                    family.id,
                    "no runnable strategy implementation yet - see "
                    "docs/AUTONOMOUS_RESEARCH_AUDIT.md known limitations",
                )
            )

    momentum_family = enabled_by_id.get("momentum_trend")
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

    cross_asset_family = enabled_by_id.get("cross_asset_regime")
    if cross_asset_family is not None:
        if _CROSS_ASSET_REFERENCE_SYMBOL not in protocol.universe.symbols:
            skipped.append(
                (
                    cross_asset_family.id,
                    f"reference symbol {_CROSS_ASSET_REFERENCE_SYMBOL!r} is not in "
                    "universe.symbols - cannot confirm a regime without it",
                )
            )
        else:
            target_symbols = [
                s for s in protocol.universe.symbols if s != _CROSS_ASSET_REFERENCE_SYMBOL
            ]
            for strategy_name, grid in _CROSS_ASSET_STRATEGIES.items():
                for symbol in target_symbols:
                    for timeframe in protocol.universe.timeframes_primary:
                        if len(queued) >= budget.max_new_hypotheses_per_cycle:
                            return HypothesisQueue(
                                queued=tuple(queued), skipped_families=tuple(skipped)
                            )
                        bounded_grid = tuple(grid[: budget.max_variants_per_hypothesis])
                        hyp = Hypothesis(
                            hypothesis_id=make_hypothesis_id(cross_asset_family.id, sequence),
                            family=cross_asset_family.id,
                            rationale=(
                                f"{cross_asset_family.description.strip()} "
                                f"Strategy: {strategy_name}. "
                                f"Reference: {_CROSS_ASSET_REFERENCE_SYMBOL}."
                            ),
                            symbols=(symbol,),
                            timeframes=(timeframe,),
                            parameters={
                                "strategy": strategy_name,
                                "param_grid": list(bounded_grid),
                                "reference_symbol": _CROSS_ASSET_REFERENCE_SYMBOL,
                            },
                        )
                        sequence += 1
                        queued.append(
                            QueuedHypothesis(
                                hypothesis=hyp,
                                strategy_name=strategy_name,
                                param_grid=bounded_grid,
                                reference_symbol=_CROSS_ASSET_REFERENCE_SYMBOL,
                            )
                        )

    funding_family = enabled_by_id.get("funding_oi")
    if funding_family is not None:
        for strategy_name, grid in _FUNDING_OI_STRATEGIES.items():
            for symbol in protocol.universe.symbols:
                for timeframe in protocol.universe.timeframes_primary:
                    if len(queued) >= budget.max_new_hypotheses_per_cycle:
                        return HypothesisQueue(
                            queued=tuple(queued), skipped_families=tuple(skipped)
                        )
                    bounded_grid = tuple(grid[: budget.max_variants_per_hypothesis])
                    hyp = Hypothesis(
                        hypothesis_id=make_hypothesis_id(funding_family.id, sequence),
                        family=funding_family.id,
                        rationale=(
                            f"{funding_family.description.strip()} Strategy: {strategy_name}."
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
