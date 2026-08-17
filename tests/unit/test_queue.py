from __future__ import annotations

from src.research.config import load_research_protocol
from src.research.queue import build_hypothesis_queue


def test_queue_respects_max_new_hypotheses_per_cycle() -> None:
    protocol = load_research_protocol()
    queue = build_hypothesis_queue(protocol)
    assert len(queue.queued) <= protocol.hypothesis_budget.max_new_hypotheses_per_cycle


def test_queue_respects_max_variants_per_hypothesis() -> None:
    protocol = load_research_protocol()
    queue = build_hypothesis_queue(protocol)
    for qh in queue.queued:
        assert len(qh.param_grid) <= protocol.hypothesis_budget.max_variants_per_hypothesis


def test_every_queued_hypothesis_has_a_rationale() -> None:
    protocol = load_research_protocol()
    queue = build_hypothesis_queue(protocol)
    for qh in queue.queued:
        assert qh.hypothesis.rationale.strip()


def test_disabled_or_unimplemented_families_are_skipped_not_faked() -> None:
    protocol = load_research_protocol()
    queue = build_hypothesis_queue(protocol)
    skipped_ids = {family_id for family_id, _reason in queue.skipped_families}
    assert "cross_asset_regime" in skipped_ids
    assert "funding_oi" in skipped_ids
    assert "portfolio_combination" in skipped_ids
    assert "microstructure" not in skipped_ids  # disabled in config, never even considered


def test_queued_hypotheses_only_use_universe_symbols_and_primary_timeframes() -> None:
    protocol = load_research_protocol()
    queue = build_hypothesis_queue(protocol)
    for qh in queue.queued:
        assert set(qh.hypothesis.symbols) <= set(protocol.universe.symbols)
        assert set(qh.hypothesis.timeframes) <= set(protocol.universe.timeframes_primary)


def test_hypothesis_ids_are_unique() -> None:
    protocol = load_research_protocol()
    queue = build_hypothesis_queue(protocol)
    ids = [qh.hypothesis.hypothesis_id for qh in queue.queued]
    assert len(ids) == len(set(ids))


def test_default_budget_covers_the_full_family_a_queue() -> None:
    """max_new_hypotheses_per_cycle is set to exactly cover one full pass
    of every implemented strategy x symbol x timeframe combination in
    family A - a lower cap previously cut trend_following out of every
    cycle silently (it never appeared in queue.queued at all)."""
    protocol = load_research_protocol()
    queue = build_hypothesis_queue(protocol)
    strategies_tested = {qh.strategy_name for qh in queue.queued}
    assert strategies_tested == {"momentum", "trend_following"}
    expected = len(protocol.universe.symbols) * len(protocol.universe.timeframes_primary) * 2
    assert len(queue.queued) == expected
