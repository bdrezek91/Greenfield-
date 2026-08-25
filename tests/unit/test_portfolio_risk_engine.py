"""Portfolio risk must fail closed and share one non-overridable budget."""

from datetime import UTC, datetime, timedelta

import pytest

from src.risk.portfolio_engine import (
    PortfolioEntryProposal,
    PortfolioPosition,
    PortfolioRiskConfig,
    PortfolioRiskDecision,
    PortfolioRiskEngine,
    PortfolioRiskSnapshot,
)

NOW = datetime(2026, 8, 23, 12, tzinfo=UTC)


def _proposal(
    key: str,
    *,
    symbol: str = "BTCUSDT",
    venue: str = "bybit",
    strategy: str = "directional-v1",
    engine_name: str = "directional",
    notional: float = 20_000.0,
    risk: float = 0.01,
    checked: tuple[str, ...] = (),
    correlated: tuple[str, ...] = (),
    at: datetime = NOW,
) -> PortfolioEntryProposal:
    return PortfolioEntryProposal(
        key=key,
        symbol=symbol,
        venue=venue,
        strategy=strategy,
        engine=engine_name,
        signed_notional=notional,
        committed_risk_fraction=risk,
        correlation_checked_symbols=checked,
        correlated_symbols=correlated,
        proposed_at_utc=at,
    )


def _open(engine: PortfolioRiskEngine, proposal: PortfolioEntryProposal) -> None:
    decision = engine.evaluate_entry(proposal, equity=100_000.0)
    assert decision.approved
    engine.record_open(proposal, decision)


def test_approves_and_records_position_with_projected_exposure() -> None:
    engine = PortfolioRiskEngine()
    proposal = _proposal("btc-long")

    decision = engine.evaluate_entry(proposal, equity=100_000.0)

    assert decision.proposal_key == proposal.key
    assert decision.approved_signed_notional == 20_000.0
    assert decision.projected_gross_exposure == 20_000.0
    assert decision.projected_net_exposure == 20_000.0
    assert decision.projected_committed_risk_fraction == 0.01
    engine.record_open(proposal, decision)
    assert engine.gross_exposure == 20_000.0
    assert engine.net_exposure == 20_000.0
    assert engine.committed_risk_fraction == 0.01
    assert engine.positions[0].key == "btc-long"


def test_clamps_notional_to_tightest_symbol_limit_and_scales_risk() -> None:
    engine = PortfolioRiskEngine(
        PortfolioRiskConfig(maximum_symbol_exposure_multiple=0.1)
    )

    decision = engine.evaluate_entry(_proposal("limited", notional=50_000.0), equity=100_000.0)

    assert decision.approved
    assert decision.approved_signed_notional == 10_000.0
    assert decision.approved_risk_fraction == pytest.approx(0.002)


def test_strategy_and_engine_budgets_are_shared_across_symbols() -> None:
    engine = PortfolioRiskEngine(
        PortfolioRiskConfig(
            maximum_strategy_exposure_multiple=0.25,
            maximum_engine_exposure_multiple=0.3,
        )
    )
    _open(engine, _proposal("btc", notional=20_000.0))

    decision = engine.evaluate_entry(
        _proposal(
            "eth",
            symbol="ETHUSDT",
            notional=20_000.0,
            checked=("BTCUSDT",),
        ),
        equity=100_000.0,
    )

    assert decision.approved_signed_notional == 5_000.0


def test_missing_correlation_coverage_blocks_second_symbol() -> None:
    engine = PortfolioRiskEngine()
    _open(engine, _proposal("btc"))

    decision = engine.evaluate_entry(
        _proposal("eth", symbol="ETHUSDT"), equity=100_000.0
    )

    assert not decision.approved
    assert decision.reason == "MISSING_CORRELATION_EVIDENCE"
    assert decision.proposal_key == "eth"


def test_correlated_beta_limit_is_shared_across_symbols() -> None:
    engine = PortfolioRiskEngine(
        PortfolioRiskConfig(maximum_correlated_exposure_multiple=0.3)
    )
    _open(engine, _proposal("btc", notional=20_000.0))

    decision = engine.evaluate_entry(
        _proposal(
            "eth",
            symbol="ETHUSDT",
            notional=20_000.0,
            checked=("BTCUSDT",),
            correlated=("BTCUSDT",),
        ),
        equity=100_000.0,
    )

    assert decision.approved
    assert decision.approved_signed_notional == 10_000.0


def test_checked_uncorrelated_symbol_does_not_consume_correlated_bucket() -> None:
    engine = PortfolioRiskEngine(
        PortfolioRiskConfig(maximum_correlated_exposure_multiple=0.25)
    )
    _open(engine, _proposal("btc", notional=20_000.0))

    decision = engine.evaluate_entry(
        _proposal(
            "sol",
            symbol="SOLUSDT",
            notional=20_000.0,
            checked=("BTCUSDT",),
        ),
        equity=100_000.0,
    )

    assert decision.approved_signed_notional == 20_000.0


def test_daily_loss_guard_resets_only_on_next_utc_day() -> None:
    engine = PortfolioRiskEngine(
        PortfolioRiskConfig(maximum_daily_loss_fraction=0.02)
    )
    position = _proposal("loss")
    _open(engine, position)
    engine.record_close("loss", realized_pnl=-2_500.0, closed_at_utc=NOW)

    blocked = engine.evaluate_entry(_proposal("same-day"), equity=100_000.0)
    next_day = engine.evaluate_entry(
        _proposal("next-day", at=NOW + timedelta(days=1)), equity=100_000.0
    )

    assert blocked.reason == "MAXIMUM_DAILY_LOSS"
    assert next_day.approved


def test_out_of_order_event_cannot_roll_daily_loss_ledger_back() -> None:
    engine = PortfolioRiskEngine(
        PortfolioRiskConfig(maximum_daily_loss_fraction=0.02)
    )
    day_two = NOW + timedelta(days=1)
    position = _proposal("loss", at=day_two)
    _open(engine, position)
    engine.record_close("loss", realized_pnl=-2_500.0, closed_at_utc=day_two)

    stale = engine.evaluate_entry(_proposal("stale", at=NOW), equity=100_000.0)
    current = engine.evaluate_entry(
        _proposal("current", at=day_two), equity=100_000.0
    )

    assert stale.reason == "OUT_OF_ORDER_TIMESTAMP"
    assert current.reason == "MAXIMUM_DAILY_LOSS"


def test_peak_to_trough_drawdown_blocks_new_risk() -> None:
    engine = PortfolioRiskEngine(
        PortfolioRiskConfig(maximum_drawdown_fraction=0.15)
    )
    engine.update_equity(100_000.0)

    decision = engine.evaluate_entry(_proposal("drawdown"), equity=84_000.0)

    assert decision.reason == "MAXIMUM_DRAWDOWN"


def test_kill_switch_requires_reasons_and_dominates_signal() -> None:
    engine = PortfolioRiskEngine()
    with pytest.raises(ValueError, match="requires a reason"):
        engine.activate_kill_switch(" ")
    engine.activate_kill_switch("venue state mismatch")

    blocked = engine.evaluate_entry(_proposal("blocked"), equity=100_000.0)

    assert engine.kill_switch_active
    assert blocked.reason == "KILL_SWITCH_ACTIVE:venue state mismatch"
    with pytest.raises(ValueError, match="operator reason"):
        engine.clear_kill_switch(operator_reason="")
    engine.clear_kill_switch(operator_reason="incident reconciled")
    assert engine.evaluate_entry(_proposal("allowed"), equity=100_000.0).approved


def test_position_count_duplicate_key_and_unknown_close_fail_closed() -> None:
    engine = PortfolioRiskEngine(PortfolioRiskConfig(maximum_open_positions=1))
    proposal = _proposal("only")
    original_decision = engine.evaluate_entry(proposal, equity=100_000.0)
    engine.record_open(proposal, original_decision)

    assert engine.evaluate_entry(_proposal("extra"), equity=100_000.0).reason == (
        "MAXIMUM_OPEN_POSITIONS"
    )
    with pytest.raises(ValueError, match="already open"):
        engine.record_open(proposal, original_decision)
    with pytest.raises(KeyError, match="unknown portfolio position"):
        engine.record_close("missing", realized_pnl=0.0, closed_at_utc=NOW)


def test_decision_cannot_be_replayed_for_another_proposal_or_mutated() -> None:
    engine = PortfolioRiskEngine()
    first = _proposal("first")
    decision = engine.evaluate_entry(first, equity=100_000.0)

    with pytest.raises(ValueError, match="does not belong"):
        engine.record_open(_proposal("second"), decision)
    forged = PortfolioRiskDecision(
        proposal_key="first",
        approved=True,
        approved_signed_notional=-20_000.0,
        approved_risk_fraction=0.01,
        reason="APPROVED",
        projected_gross_exposure=20_000.0,
        projected_net_exposure=-20_000.0,
        projected_committed_risk_fraction=0.01,
    )
    with pytest.raises(ValueError, match="not issued by this engine"):
        engine.record_open(first, forged)


def test_snapshot_restores_exposure_loss_peak_and_kill_switch() -> None:
    engine = PortfolioRiskEngine(PortfolioRiskConfig(maximum_daily_loss_fraction=0.02))
    _open(engine, _proposal("btc"))
    engine.update_equity(120_000.0)
    engine.activate_kill_switch("manual incident hold")

    restored = PortfolioRiskEngine.from_snapshot(engine.snapshot(), engine.config)

    assert restored.gross_exposure == 20_000.0
    assert restored.kill_switch_active
    restored.clear_kill_switch(operator_reason="state reconciled")
    assert restored.evaluate_entry(_proposal("drawdown"), equity=100_000.0).reason == (
        "MAXIMUM_DRAWDOWN"
    )


def test_snapshot_validation_rejects_duplicates_and_limit_mismatch() -> None:
    position = PortfolioPosition(
        key="same",
        symbol="BTCUSDT",
        venue="bybit",
        strategy="directional-v1",
        engine="directional",
        signed_notional=1_000.0,
        committed_risk_fraction=0.001,
        opened_at_utc=NOW,
    )
    with pytest.raises(ValueError, match="keys must be unique"):
        PortfolioRiskSnapshot(
            positions=(position, position),
            peak_equity=100_000.0,
            daily_realized_pnl=0.0,
            current_day=NOW.date(),
            kill_switch_reason=None,
        )

    snapshot = PortfolioRiskSnapshot(
        positions=(
            position,
            PortfolioPosition(
                key="second",
                symbol="ETHUSDT",
                venue="okx",
                strategy="neutral-v1",
                engine="neutral",
                signed_notional=-1_000.0,
                committed_risk_fraction=0.001,
                opened_at_utc=NOW,
            ),
        ),
        peak_equity=100_000.0,
        daily_realized_pnl=0.0,
        current_day=NOW.date(),
        kill_switch_reason=None,
    )
    with pytest.raises(ValueError, match="configured position limit"):
        PortfolioRiskEngine.from_snapshot(
            snapshot, PortfolioRiskConfig(maximum_open_positions=1)
        )


def test_invalid_config_is_rejected() -> None:
    with pytest.raises(ValueError, match="finite and positive"):
        PortfolioRiskConfig(maximum_gross_exposure_multiple=0.0)
    with pytest.raises(ValueError, match="at least one position"):
        PortfolioRiskConfig(maximum_open_positions=0)


def test_invalid_proposals_and_equity_are_rejected() -> None:
    with pytest.raises(ValueError, match="covered by correlation evidence"):
        _proposal("bad-correlation", correlated=("BTCUSDT",))
    with pytest.raises(ValueError, match="must not appear"):
        _proposal("self", checked=("BTCUSDT",))
    with pytest.raises(ValueError, match="timezone-aware"):
        _proposal("naive", at=datetime(2026, 8, 23, 12))
    with pytest.raises(ValueError, match="equity"):
        PortfolioRiskEngine().evaluate_entry(_proposal("bad-equity"), equity=0.0)
