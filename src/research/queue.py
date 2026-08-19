"""Build the complete, bounded A-G hypothesis queue for one research cycle.

The versioned protocol controls both the enabled families and hard search
budget. Each queue row is one symbol/timeframe hypothesis with a small fixed
grid; cross-sectional rows explicitly name every peer dataset they consume.
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

def _grid_for_timeframe(grid: list[dict], timeframe: str, limit: int) -> tuple[dict, ...]:
    """Attach a holding horizon that is feasible inside one TEST segment.

    A 24-bar hold is four days on 4h, but twenty-four days on 1d and was
    longer than the protocol's 21-day TEST window.  The old configuration
    therefore made ``min_oos_trades=30`` mathematically unreachable on 1d.
    Seven daily bars retains a multi-day thesis while allowing at least two
    complete round trips per fold after a one-bar execution delay.
    """
    holding_period_bars = 7 if timeframe == "1d" else 24
    return tuple(
        {**params, "holding_period_bars": holding_period_bars} for params in grid[:limit]
    )


@dataclass(frozen=True)
class QueuedHypothesis:
    hypothesis: Hypothesis
    strategy_name: str
    param_grid: tuple[dict, ...]
    reference_symbol: str | None = None
    """Legacy single reference used by the older cross-asset strategy."""
    reference_symbols: tuple[str, ...] = ()
    """All peer datasets loaded for a cross-sectional hypothesis."""


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
    enabled = {family.id: family for family in protocol.enabled_families()}

    def bars(days: int, timeframe: str) -> int:
        return days * 6 if timeframe == "4h" else days

    def add(
        family_id: str,
        strategy: str,
        symbol: str,
        timeframe: str,
        grid: list[dict],
        references: tuple[str, ...] = (),
    ) -> None:
        nonlocal sequence
        family = enabled.get(family_id)
        if family is None or len(queued) >= budget.max_new_hypotheses_per_cycle:
            return
        bounded = _grid_for_timeframe(grid, timeframe, budget.max_variants_per_hypothesis)
        hypothesis = Hypothesis(
            hypothesis_id=make_hypothesis_id(family_id, sequence),
            family=family_id,
            rationale=f"{family.description.strip()} Strategy: {strategy}.",
            symbols=(symbol,),
            timeframes=(timeframe,),
            parameters={
                "strategy": strategy,
                "param_grid": list(bounded),
                "reference_symbols": list(references),
            },
        )
        sequence += 1
        queued.append(
            QueuedHypothesis(
                hypothesis=hypothesis,
                strategy_name=strategy,
                param_grid=bounded,
                reference_symbols=references,
            )
        )

    symbols = tuple(protocol.universe.symbols)
    for timeframe in protocol.universe.timeframes_primary:
        add(
            "btc_time_series_momentum",
            "momentum",
            "BTCUSDT",
            timeframe,
            [
                {"lookback_bars": bars(days, timeframe), "threshold": 0.0}
                for days in (7, 30, 90, 180)
            ],
        )
        for symbol in symbols:
            add(
                "multi_asset_time_series_momentum",
                "momentum",
                symbol,
                timeframe,
                [
                    {"lookback_bars": bars(days, timeframe), "threshold": 0.0}
                    for days in (30, 90, 180)
                ],
            )
            peers = tuple(peer for peer in symbols if peer != symbol)
            add(
                "cross_sectional_momentum",
                "cross_sectional_momentum",
                symbol,
                timeframe,
                [
                    {"lookback_bars": bars(days, timeframe), "top_fraction": 0.34}
                    for days in (30, 90)
                ],
                peers,
            )
            add(
                "donchian_trend_following",
                "breakout",
                symbol,
                timeframe,
                [{"lookback_bars": bars(days, timeframe)} for days in (20, 60, 120)],
            )
            annualizer = 365.25 * (6 if timeframe == "4h" else 1)
            add(
                "trend_volatility_targeting",
                "trend_following",
                symbol,
                timeframe,
                [
                    {
                        "lookback_bars": bars(90, timeframe),
                        "volatility_target": target / annualizer**0.5,
                    }
                    for target in (0.15, 0.25)
                ],
            )
            add(
                "cross_sectional_volatility_targeting",
                "cross_sectional_momentum",
                symbol,
                timeframe,
                [
                    {
                        "lookback_bars": bars(90, timeframe),
                        "top_fraction": 0.34,
                        "volatility_target": target / annualizer**0.5,
                    }
                    for target in (0.15, 0.25)
                ],
                peers,
            )
            add(
                "funding_carry",
                "funding_carry",
                symbol,
                timeframe,
                [
                    {"persistence_observations": 3, "min_abs_funding_rate": 0.00003},
                    {"persistence_observations": 6, "min_abs_funding_rate": 0.00005},
                ],
            )
            add(
                "cross_sectional_funding_carry",
                "cross_sectional_funding_carry",
                symbol,
                timeframe,
                [
                    {"persistence_observations": 3, "top_fraction": 0.34},
                    {"persistence_observations": 6, "top_fraction": 0.34},
                ],
                peers,
            )
            add(
                "mean_reversion",
                "mean_reversion",
                symbol,
                timeframe,
                [
                    {"lookback_bars": 10, "threshold": 0.02},
                    {"lookback_bars": 20, "threshold": 0.02},
                    {"lookback_bars": 20, "threshold": 0.04},
                ],
            )
            add(
                "funding_oi_contrarian",
                "funding_contrarian",
                symbol,
                timeframe,
                [
                    {"funding_zscore_lookback": 30, "funding_zscore_threshold": 1.5},
                    {"funding_zscore_lookback": 60, "funding_zscore_threshold": 2.0},
                ],
            )
            add(
                "long_short_ratio_contrarian",
                "long_short_ratio_contrarian",
                symbol,
                timeframe,
                [
                    {"period": "5min", "zscore_lookback": 30, "zscore_threshold": 1.5},
                    {"period": "5min", "zscore_lookback": 60, "zscore_threshold": 2.0},
                ],
            )

    known = {
        "btc_time_series_momentum",
        "multi_asset_time_series_momentum",
        "cross_sectional_momentum",
        "donchian_trend_following",
        "trend_volatility_targeting",
        "cross_sectional_volatility_targeting",
        "funding_carry",
        "cross_sectional_funding_carry",
        "mean_reversion",
        "funding_oi_contrarian",
        "long_short_ratio_contrarian",
    }
    skipped.extend(
        (family_id, "enabled family has no A-G queue definition")
        for family_id in enabled
        if family_id not in known
    )
    return HypothesisQueue(tuple(queued), tuple(skipped))
