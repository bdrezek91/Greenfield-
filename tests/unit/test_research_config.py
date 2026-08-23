"""configs/research_protocol.yaml parses into a fully-typed ResearchProtocol."""

from __future__ import annotations

import pytest

from src.research.config import DEFAULT_PROTOCOL_PATH, load_research_protocol


def test_default_protocol_loads() -> None:
    protocol = load_research_protocol()
    assert protocol.version >= 1
    assert "BTCUSDT" in protocol.universe.symbols
    assert protocol.is_symbol_allowed("BTCUSDT")
    assert not protocol.is_symbol_allowed("NOTASYMBOL")


def test_primary_timeframes_are_4h_and_1d() -> None:
    protocol = load_research_protocol()
    assert set(protocol.universe.timeframes_primary) == {"4h", "1d"}
    assert "15m" in protocol.universe.timeframes_disabled


def test_enabled_families_excludes_microstructure_by_default() -> None:
    protocol = load_research_protocol()
    enabled_ids = {f.id for f in protocol.enabled_families()}
    assert "microstructure" not in enabled_ids
    assert "momentum_trend" in enabled_ids


def test_cost_scenarios_are_ordered_base_lt_adverse_lt_severe() -> None:
    protocol = load_research_protocol()
    costs = protocol.costs
    assert costs.base.slippage_multiplier < costs.adverse.slippage_multiplier
    assert costs.adverse.slippage_multiplier < costs.severe.slippage_multiplier
    assert costs.base.entry_delay_bars <= costs.adverse.entry_delay_bars
    assert costs.adverse.entry_delay_bars <= costs.severe.entry_delay_bars


def test_promotion_gate_requires_funding_and_mark_to_market() -> None:
    protocol = load_research_protocol()
    assert protocol.promotion_gate.requires_funding_applied is True
    assert protocol.promotion_gate.requires_mark_to_market is True
    assert protocol.promotion_gate.requires_complete_data is True


def test_paper_promotion_requires_human_approval() -> None:
    protocol = load_research_protocol()
    assert protocol.paper_promotion.requires_human_approval is True


def test_holdout_has_a_stable_frozen_id() -> None:
    protocol = load_research_protocol()
    assert protocol.holdout.enabled is True
    assert protocol.holdout.holdout_id


def test_default_protocol_caps_lookback_history() -> None:
    """Bounds walk-forward window count regardless of how much history is
    on disk - see configs/research_protocol.yaml's max_lookback_days."""
    protocol = load_research_protocol()
    assert protocol.data_split.max_lookback_days == 730


def test_bad_protocol_file_raises(tmp_path) -> None:
    bad = tmp_path / "bad.yaml"
    bad.write_text("version: 1\nuniverse: {}\n")
    with pytest.raises(KeyError):
        load_research_protocol(bad)


def test_negative_min_dsr_is_rejected(tmp_path) -> None:
    import shutil

    bad = tmp_path / "bad_protocol.yaml"
    shutil.copy(DEFAULT_PROTOCOL_PATH, bad)
    text = bad.read_text().replace(
        "min_deflated_sharpe_ratio: 0.95", "min_deflated_sharpe_ratio: -1.0"
    )
    bad.write_text(text)
    with pytest.raises(ValueError, match="non-negative"):
        load_research_protocol(bad)


def test_default_protocol_pct_fields_consumed_by_degradation_are_0_100_scale() -> None:
    """src.research.degradation compares these against 0-100 observed/derived
    percentages (see that module) - a value like 0.40 here would silently
    make every degradation check vacuously pass. Locks in the Cycle 6 fix.
    """
    protocol = load_research_protocol()
    assert protocol.paper_promotion.max_signal_frequency_deviation_pct == 40.0
    assert protocol.paper_promotion.min_fill_rate_pct == 90.0
    assert protocol.retirement.max_paper_drawdown_pct == 25.0


@pytest.mark.parametrize(
    "needle,replacement",
    [
        ("max_signal_frequency_deviation_pct: 40.0", "max_signal_frequency_deviation_pct: 140.0"),
        ("min_fill_rate_pct: 90.0", "min_fill_rate_pct: -1.0"),
        ("max_paper_drawdown_pct: 25.0", "max_paper_drawdown_pct: 250.0"),
    ],
)
def test_pct_field_out_of_0_100_range_is_rejected(tmp_path, needle: str, replacement: str) -> None:
    import shutil

    bad = tmp_path / "bad_protocol.yaml"
    shutil.copy(DEFAULT_PROTOCOL_PATH, bad)
    text = bad.read_text()
    assert needle in text, f"fixture assumption stale: {needle!r} not found in default protocol"
    bad.write_text(text.replace(needle, replacement))
    with pytest.raises(ValueError, match="0-100 percentage scale"):
        load_research_protocol(bad)
