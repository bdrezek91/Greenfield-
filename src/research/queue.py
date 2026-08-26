"""Build the bounded hypothesis queue for one research cycle.

Per the brief: the queue must stay a small, economically-motivated set of
families (ETAP 2 A-E), never an unconstrained indicator/parameter search.
Every cap here comes from `configs/research_protocol.yaml` - nothing is
hardcoded independently of it.

Family A (time-series momentum/trend: `momentum`, `trend_following`),
family B (cross-asset/regime confirmation: `cross_asset_momentum`, BTC as
a trend filter for other symbols), family C (funding/OI contrarian:
`funding_contrarian`, extreme funding confirmed by rising open interest),
and family F (price-action confluence: `liquidity_sweep_confluence`, a
mechanical liquidity-sweep reversal confirmed by rising open interest)
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

_PRICE_ACTION_STRATEGIES: dict[str, list[dict]] = {
    "liquidity_sweep_confluence": [
        {"structure_lookback": 10, "oi_confirmation_bars": 5},
        {"structure_lookback": 20, "oi_confirmation_bars": 5},
    ],
}

# Family G. Fixed base/confirming timeframe pair (4h primary, 1d
# confirming) per the frozen prereg - this is not a generic per-timeframe
# grid like the families above, it's specifically about that pair, so
# there is no per-timeframe loop for this family in build_hypothesis_queue
# below. Exactly the 12 variants frozen in
# docs/PREREGISTRATION_funding_aware_multi_horizon_trend.md - do not add,
# remove, or reorder without a new preregistration.
_MULTI_HORIZON_TREND_BASE_TIMEFRAME = "4h"
_MULTI_HORIZON_TREND_CONFIRMING_TIMEFRAME = "1d"
_MULTI_HORIZON_TREND_STRATEGIES: dict[str, list[dict]] = {
    "funding_aware_multi_horizon_trend": [
        {"lookback_bars_4h": lookback_4h, "lookback_bars_1d": lookback_1d, "volatility_target": vt}
        for lookback_4h in (30, 60, 90)
        for lookback_1d in (10, 20)
        for vt in (0.15, 0.25)
    ],
}

# Family H. Exactly the 3 variants frozen in
# docs/PREREGISTRATION_market_cipher_like.md - do not add, remove, or
# reorder without a new preregistration. `timeframe` is not baked in here
# (unlike the other grids above) because MarketCipherLikeConfig needs it to
# match whichever timeframe a given hypothesis actually trades - it is
# merged into each variant per timeframe in build_hypothesis_queue below.
_MARKET_CIPHER_LIKE_STRATEGIES: dict[str, list[dict]] = {
    "market_cipher_like": [
        {"channel_span": 9, "momentum_span": 13, "signal_window": 4},
        {"channel_span": 10, "momentum_span": 21, "signal_window": 4},
        {"channel_span": 10, "momentum_span": 21, "signal_window": 8},
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
    higher_timeframe: str | None = None
    """Set for family G (funding_aware_multi_horizon_trend) hypotheses -
    the SAME symbol's confirming higher timeframe (1d), as distinct from
    reference_symbol above (a different instrument)."""


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
        if family.id not in (
            "momentum_trend",
            "cross_asset_regime",
            "funding_oi",
            "price_action_confluence",
            "funding_aware_multi_horizon_trend",
            "market_cipher_like",
        ):
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

    price_action_family = enabled_by_id.get("price_action_confluence")
    if price_action_family is not None:
        for strategy_name, grid in _PRICE_ACTION_STRATEGIES.items():
            for symbol in protocol.universe.symbols:
                for timeframe in protocol.universe.timeframes_primary:
                    if len(queued) >= budget.max_new_hypotheses_per_cycle:
                        return HypothesisQueue(
                            queued=tuple(queued), skipped_families=tuple(skipped)
                        )
                    bounded_grid = tuple(grid[: budget.max_variants_per_hypothesis])
                    hyp = Hypothesis(
                        hypothesis_id=make_hypothesis_id(price_action_family.id, sequence),
                        family=price_action_family.id,
                        rationale=(
                            f"{price_action_family.description.strip()} Strategy: {strategy_name}."
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

    multi_horizon_family = enabled_by_id.get("funding_aware_multi_horizon_trend")
    if multi_horizon_family is not None:
        if _MULTI_HORIZON_TREND_BASE_TIMEFRAME not in protocol.universe.timeframes_primary:
            skipped.append(
                (
                    multi_horizon_family.id,
                    f"base timeframe {_MULTI_HORIZON_TREND_BASE_TIMEFRAME!r} is not in "
                    "universe.timeframes_primary",
                )
            )
        elif _MULTI_HORIZON_TREND_CONFIRMING_TIMEFRAME not in protocol.universe.timeframes_primary:
            skipped.append(
                (
                    multi_horizon_family.id,
                    f"confirming timeframe {_MULTI_HORIZON_TREND_CONFIRMING_TIMEFRAME!r} is "
                    "not in universe.timeframes_primary",
                )
            )
        else:
            for strategy_name, grid in _MULTI_HORIZON_TREND_STRATEGIES.items():
                for symbol in protocol.universe.symbols:
                    if len(queued) >= budget.max_new_hypotheses_per_cycle:
                        return HypothesisQueue(
                            queued=tuple(queued), skipped_families=tuple(skipped)
                        )
                    bounded_grid = tuple(grid[: budget.max_variants_per_hypothesis])
                    hyp = Hypothesis(
                        hypothesis_id=make_hypothesis_id(multi_horizon_family.id, sequence),
                        family=multi_horizon_family.id,
                        rationale=(
                            f"{multi_horizon_family.description.strip()} "
                            f"Strategy: {strategy_name}. "
                            f"Base: {_MULTI_HORIZON_TREND_BASE_TIMEFRAME}, "
                            f"confirming: {_MULTI_HORIZON_TREND_CONFIRMING_TIMEFRAME}."
                        ),
                        symbols=(symbol,),
                        timeframes=(
                            _MULTI_HORIZON_TREND_BASE_TIMEFRAME,
                            _MULTI_HORIZON_TREND_CONFIRMING_TIMEFRAME,
                        ),
                        parameters={
                            "strategy": strategy_name,
                            "param_grid": list(bounded_grid),
                            "higher_timeframe": _MULTI_HORIZON_TREND_CONFIRMING_TIMEFRAME,
                        },
                    )
                    sequence += 1
                    queued.append(
                        QueuedHypothesis(
                            hypothesis=hyp,
                            strategy_name=strategy_name,
                            param_grid=bounded_grid,
                            higher_timeframe=_MULTI_HORIZON_TREND_CONFIRMING_TIMEFRAME,
                        )
                    )

    market_cipher_family = enabled_by_id.get("market_cipher_like")
    if market_cipher_family is not None:
        for strategy_name, grid in _MARKET_CIPHER_LIKE_STRATEGIES.items():
            for symbol in protocol.universe.symbols:
                for timeframe in protocol.universe.timeframes_primary:
                    if len(queued) >= budget.max_new_hypotheses_per_cycle:
                        return HypothesisQueue(
                            queued=tuple(queued), skipped_families=tuple(skipped)
                        )
                    # `timeframe` merged per-variant here (not baked into
                    # the static grid above) - MarketCipherLikeConfig needs
                    # it to match whichever timeframe this hypothesis
                    # actually trades.
                    bounded_grid = tuple(
                        {**variant, "timeframe": timeframe}
                        for variant in grid[: budget.max_variants_per_hypothesis]
                    )
                    hyp = Hypothesis(
                        hypothesis_id=make_hypothesis_id(market_cipher_family.id, sequence),
                        family=market_cipher_family.id,
                        rationale=(
                            f"{market_cipher_family.description.strip()} "
                            f"Strategy: {strategy_name}."
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
