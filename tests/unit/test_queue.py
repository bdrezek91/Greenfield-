from __future__ import annotations

from dataclasses import replace

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
    # cross_asset_regime, funding_oi, and price_action_confluence now have
    # runnable strategies (CrossAssetMomentum, FundingContrarian,
    # LiquiditySweepConfluence) - they may still produce 0 hypotheses THIS
    # cycle if the default budget is fully consumed by earlier families
    # first, but that's a budget effect, not "unimplemented", so none must
    # ever appear in skipped_families.
    assert "cross_asset_regime" not in skipped_ids
    assert "funding_oi" not in skipped_ids
    assert "price_action_confluence" not in skipped_ids
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


def test_default_budget_covers_every_implemented_strategy() -> None:
    """max_new_hypotheses_per_cycle is set to exactly cover one full pass
    of every implemented strategy in families A, B, C, F, and G - a lower
    cap previously cut whole strategies out of every cycle silently (never
    appeared in queue.queued at all, not even as "skipped")."""
    protocol = load_research_protocol()
    queue = build_hypothesis_queue(protocol)
    strategies_tested = {qh.strategy_name for qh in queue.queued}
    assert strategies_tested == {
        "momentum",
        "trend_following",
        "cross_asset_momentum",
        "funding_contrarian",
        "liquidity_sweep_confluence",
        "funding_aware_multi_horizon_trend",
        "market_cipher_like",
    }

    family_a_expected = (
        len(protocol.universe.symbols) * len(protocol.universe.timeframes_primary) * 2
    )
    non_reference_symbols = len(protocol.universe.symbols) - 1  # BTCUSDT is the reference
    family_b_expected = non_reference_symbols * len(protocol.universe.timeframes_primary)
    family_c_expected = len(protocol.universe.symbols) * len(protocol.universe.timeframes_primary)
    family_f_expected = len(protocol.universe.symbols) * len(protocol.universe.timeframes_primary)
    # Family G (funding_aware_multi_horizon_trend) is one hypothesis per
    # symbol at the fixed 4h/1d horizon pair, not per timeframes_primary
    # entry - see src/research/queue.py's _MULTI_HORIZON_TREND_* constants.
    family_g_expected = len(protocol.universe.symbols)
    # Family H (market_cipher_like) is one hypothesis per symbol per
    # timeframes_primary entry, same shape as family A/C/F.
    family_h_expected = len(protocol.universe.symbols) * len(protocol.universe.timeframes_primary)
    assert len(queue.queued) == (
        family_a_expected
        + family_b_expected
        + family_c_expected
        + family_f_expected
        + family_g_expected
        + family_h_expected
    )


def _protocol_with_budget(max_new_hypotheses_per_cycle: int):
    protocol = load_research_protocol()
    return replace(
        protocol,
        hypothesis_budget=replace(
            protocol.hypothesis_budget,
            max_new_hypotheses_per_cycle=max_new_hypotheses_per_cycle,
        ),
    )


def test_cross_asset_hypotheses_appear_once_budget_allows() -> None:
    protocol = _protocol_with_budget(100)
    queue = build_hypothesis_queue(protocol)
    cross_asset = [qh for qh in queue.queued if qh.hypothesis.family == "cross_asset_regime"]
    assert cross_asset
    for qh in cross_asset:
        assert qh.strategy_name == "cross_asset_momentum"
        assert qh.reference_symbol == "BTCUSDT"
        assert "BTCUSDT" not in qh.hypothesis.symbols  # BTC is the reference, never the target


def test_cross_asset_queue_never_targets_the_reference_symbol_itself() -> None:
    protocol = _protocol_with_budget(100)
    queue = build_hypothesis_queue(protocol)
    for qh in queue.queued:
        if qh.hypothesis.family == "cross_asset_regime":
            assert qh.hypothesis.symbols[0] != "BTCUSDT"


def test_cross_asset_family_skipped_if_reference_symbol_not_in_universe() -> None:
    protocol = _protocol_with_budget(100)
    protocol = replace(
        protocol,
        universe=replace(protocol.universe, symbols=("ETHUSDT", "SOLUSDT")),
    )
    queue = build_hypothesis_queue(protocol)
    skipped_ids = {family_id for family_id, _reason in queue.skipped_families}
    assert "cross_asset_regime" in skipped_ids
    assert not any(qh.hypothesis.family == "cross_asset_regime" for qh in queue.queued)


def test_funding_oi_hypotheses_appear_once_budget_allows() -> None:
    protocol = _protocol_with_budget(100)
    queue = build_hypothesis_queue(protocol)
    funding = [qh for qh in queue.queued if qh.hypothesis.family == "funding_oi"]
    assert funding
    for qh in funding:
        assert qh.strategy_name == "funding_contrarian"
        assert qh.reference_symbol is None  # unlike family B, no cross-symbol reference


def test_funding_oi_covers_every_universe_symbol_not_just_non_btc() -> None:
    """Unlike family B, family C has no reference-symbol exclusion -
    funding/OI positioning is a per-symbol property, so BTCUSDT is a valid
    target here even though it is family B's reference."""
    protocol = _protocol_with_budget(100)
    queue = build_hypothesis_queue(protocol)
    funding_symbols = {
        qh.hypothesis.symbols[0] for qh in queue.queued if qh.hypothesis.family == "funding_oi"
    }
    assert funding_symbols == set(protocol.universe.symbols)


def test_price_action_confluence_hypotheses_appear_once_budget_allows() -> None:
    protocol = _protocol_with_budget(100)
    queue = build_hypothesis_queue(protocol)
    price_action = [qh for qh in queue.queued if qh.hypothesis.family == "price_action_confluence"]
    assert price_action
    for qh in price_action:
        assert qh.strategy_name == "liquidity_sweep_confluence"
        assert qh.reference_symbol is None  # no cross-symbol reference, same as family C


def test_price_action_confluence_covers_every_universe_symbol() -> None:
    protocol = _protocol_with_budget(100)
    queue = build_hypothesis_queue(protocol)
    symbols = {
        qh.hypothesis.symbols[0]
        for qh in queue.queued
        if qh.hypothesis.family == "price_action_confluence"
    }
    assert symbols == set(protocol.universe.symbols)


def test_market_cipher_like_hypotheses_appear_once_budget_allows() -> None:
    protocol = _protocol_with_budget(100)
    queue = build_hypothesis_queue(protocol)
    market_cipher = [qh for qh in queue.queued if qh.hypothesis.family == "market_cipher_like"]
    assert market_cipher
    for qh in market_cipher:
        assert qh.strategy_name == "market_cipher_like"
        assert qh.reference_symbol is None  # no cross-symbol reference, same as family C/F


def test_market_cipher_like_covers_every_universe_symbol_and_primary_timeframe() -> None:
    protocol = _protocol_with_budget(100)
    queue = build_hypothesis_queue(protocol)
    seen = {
        (qh.hypothesis.symbols[0], qh.hypothesis.timeframes[0])
        for qh in queue.queued
        if qh.hypothesis.family == "market_cipher_like"
    }
    expected = {
        (symbol, timeframe)
        for symbol in protocol.universe.symbols
        for timeframe in protocol.universe.timeframes_primary
    }
    assert seen == expected


def test_market_cipher_like_variants_carry_the_matching_timeframe() -> None:
    """Each variant's `timeframe` config kwarg must match the hypothesis's
    own timeframe - MarketCipherLikeConfig uses it to shift klines to
    close-time availability for that exact timeframe, a mismatch would
    silently corrupt the feature computation."""
    protocol = _protocol_with_budget(100)
    queue = build_hypothesis_queue(protocol)
    for qh in queue.queued:
        if qh.hypothesis.family != "market_cipher_like":
            continue
        (timeframe,) = qh.hypothesis.timeframes
        for variant in qh.param_grid:
            assert variant["timeframe"] == timeframe
