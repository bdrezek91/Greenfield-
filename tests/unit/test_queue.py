from __future__ import annotations

from dataclasses import replace

from src.research.config import load_research_protocol
from src.research.orchestrator import _required_warmup_bars
from src.research.queue import build_hypothesis_queue

EXPECTED_FAMILIES = {
    "btc_time_series_momentum",
    "multi_asset_time_series_momentum",
    "cross_sectional_momentum",
    "donchian_trend_following",
    "trend_volatility_targeting",
    "cross_sectional_volatility_targeting",
    "funding_carry",
}


def test_default_queue_is_a_complete_bounded_a_to_g_pass() -> None:
    protocol = load_research_protocol()
    queue = build_hypothesis_queue(protocol)

    assert len(queue.queued) == 38
    assert len(queue.queued) == protocol.hypothesis_budget.max_new_hypotheses_per_cycle
    assert {qh.hypothesis.family for qh in queue.queued} == EXPECTED_FAMILIES
    assert queue.skipped_families == ()
    assert len({qh.hypothesis.hypothesis_id for qh in queue.queued}) == len(queue.queued)


def test_queue_respects_variant_and_cycle_budgets() -> None:
    protocol = load_research_protocol()
    limited = replace(
        protocol,
        hypothesis_budget=replace(
            protocol.hypothesis_budget,
            max_new_hypotheses_per_cycle=5,
            max_variants_per_hypothesis=2,
        ),
    )
    queue = build_hypothesis_queue(limited)
    assert len(queue.queued) == 5
    assert all(len(qh.param_grid) <= 2 for qh in queue.queued)


def test_cross_sectional_hypotheses_load_every_other_universe_symbol() -> None:
    protocol = load_research_protocol()
    queue = build_hypothesis_queue(protocol)
    cross_sectional = [
        qh for qh in queue.queued if qh.hypothesis.family == "cross_sectional_momentum"
    ]
    assert cross_sectional
    for qh in cross_sectional:
        target = qh.hypothesis.symbols[0]
        assert set(qh.reference_symbols) == set(protocol.universe.symbols) - {target}
        assert qh.reference_symbol is None


def test_daily_holding_horizon_is_shorter_than_test_segment() -> None:
    protocol = load_research_protocol()
    daily = [
        qh
        for qh in build_hypothesis_queue(protocol).queued
        if qh.hypothesis.timeframes == ("1d",)
    ]
    assert daily
    assert all(params["holding_period_bars"] == 7 for qh in daily for params in qh.param_grid)


def test_every_hypothesis_has_rationale_and_stays_in_universe() -> None:
    protocol = load_research_protocol()
    for qh in build_hypothesis_queue(protocol).queued:
        assert qh.hypothesis.rationale.strip()
        assert set(qh.hypothesis.symbols) <= set(protocol.universe.symbols)
        assert set(qh.hypothesis.timeframes) <= set(protocol.universe.timeframes_primary)


def test_warmup_covers_the_longest_180_day_4h_lookback() -> None:
    protocol = load_research_protocol()
    hypothesis = next(
        qh
        for qh in build_hypothesis_queue(protocol).queued
        if qh.hypothesis.family == "btc_time_series_momentum"
        and qh.hypothesis.timeframes == ("4h",)
    )
    assert _required_warmup_bars(hypothesis.param_grid) >= 180 * 6 + 2
