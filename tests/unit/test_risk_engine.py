"""RiskEngine must gate entries and size positions exactly per RiskConfig,
independent of any running backtest engine.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from src.backtesting.instruments import build_crypto_perpetual, load_instrument_specs
from src.risk.engine import RiskConfig, RiskEngine


@pytest.fixture
def instrument():
    specs = load_instrument_specs()
    return build_crypto_perpetual("BTCUSDT", specs)


def _now(day: int = 1) -> datetime:
    return datetime(2024, 1, day, 12, 0, tzinfo=UTC)


def test_approves_and_sizes_by_risk_per_trade(instrument) -> None:
    engine = RiskEngine(RiskConfig(risk_per_trade=0.1, max_portfolio_risk=0.5))
    decision = engine.evaluate(instrument=instrument, price=50_000.0, equity=100_000.0, now=_now())

    assert decision.approved
    assert decision.risk_fraction == pytest.approx(0.1)
    # 10% of 100,000 = 10,000 notional / 50,000 price = 0.2 units.
    assert decision.quantity.as_double() == pytest.approx(0.2, abs=1e-9)


def test_rejects_when_max_concurrent_positions_reached(instrument) -> None:
    engine = RiskEngine(RiskConfig(max_concurrent_positions=1, max_portfolio_risk=0.5))
    engine.open_position("BTCUSDT", risk_fraction=0.1)

    decision = engine.evaluate(instrument=instrument, price=50_000.0, equity=100_000.0, now=_now())
    assert not decision.approved
    assert "max_concurrent_positions" in decision.reason


def test_rejects_when_max_portfolio_risk_exhausted(instrument) -> None:
    engine = RiskEngine(
        RiskConfig(risk_per_trade=0.1, max_portfolio_risk=0.1, max_concurrent_positions=5)
    )
    engine.open_position("ETHUSDT", risk_fraction=0.1)  # budget fully committed

    decision = engine.evaluate(instrument=instrument, price=50_000.0, equity=100_000.0, now=_now())
    assert not decision.approved
    assert "max_portfolio_risk" in decision.reason


def test_available_risk_caps_size_below_risk_per_trade(instrument) -> None:
    engine = RiskEngine(
        RiskConfig(risk_per_trade=0.1, max_portfolio_risk=0.15, max_concurrent_positions=5)
    )
    engine.open_position("ETHUSDT", risk_fraction=0.1)  # only 0.05 left of the 0.15 budget

    decision = engine.evaluate(instrument=instrument, price=50_000.0, equity=100_000.0, now=_now())
    assert decision.approved
    assert decision.risk_fraction == pytest.approx(0.05)


def test_rejects_when_daily_loss_breached(instrument) -> None:
    engine = RiskEngine(RiskConfig(max_daily_loss=0.02, max_portfolio_risk=0.5))
    engine.open_position("BTCUSDT", risk_fraction=0.1)
    engine.close_position("BTCUSDT", realized_pnl=-3000.0, now=_now())  # -3% of 100,000 > 2% limit

    decision = engine.evaluate(instrument=instrument, price=50_000.0, equity=97_000.0, now=_now())
    assert not decision.approved
    assert "max_daily_loss" in decision.reason


def test_daily_loss_resets_on_a_new_day(instrument) -> None:
    engine = RiskEngine(RiskConfig(max_daily_loss=0.02, max_portfolio_risk=0.5))
    engine.open_position("BTCUSDT", risk_fraction=0.1)
    engine.close_position("BTCUSDT", realized_pnl=-3000.0, now=_now(day=1))

    # Still breached on the same day.
    same_day = engine.evaluate(
        instrument=instrument, price=50_000.0, equity=97_000.0, now=_now(day=1)
    )
    assert not same_day.approved

    # A new UTC day resets the daily-loss counter.
    next_day = engine.evaluate(
        instrument=instrument, price=50_000.0, equity=97_000.0, now=_now(day=2)
    )
    assert next_day.approved


def test_rejects_when_max_drawdown_breached(instrument) -> None:
    engine = RiskEngine(RiskConfig(max_drawdown=0.2, max_portfolio_risk=0.5))
    # First call sets the peak equity.
    engine.evaluate(instrument=instrument, price=50_000.0, equity=100_000.0, now=_now())

    decision = engine.evaluate(instrument=instrument, price=50_000.0, equity=79_000.0, now=_now())
    assert not decision.approved
    assert "max_drawdown" in decision.reason


def test_leverage_cap_limits_notional(instrument) -> None:
    engine = RiskEngine(
        RiskConfig(risk_per_trade=0.5, max_portfolio_risk=0.9, max_leverage=0.2)
    )
    decision = engine.evaluate(instrument=instrument, price=50_000.0, equity=100_000.0, now=_now())
    assert decision.approved
    # Capped at 0.2x equity = 20,000 notional -> 0.4 units, not 0.5*100,000/50,000=1.0.
    assert decision.quantity.as_double() == pytest.approx(0.4, abs=1e-9)


def test_volatility_targeting_scales_risk(instrument) -> None:
    engine = RiskEngine(
        RiskConfig(risk_per_trade=0.1, volatility_target=0.01, max_portfolio_risk=1.0)
    )
    low_vol = engine.evaluate(
        instrument=instrument, price=50_000.0, equity=100_000.0, now=_now(), realized_vol=0.005
    )
    high_vol = engine.evaluate(
        instrument=instrument, price=50_000.0, equity=100_000.0, now=_now(), realized_vol=0.05
    )
    # Lower realized vol -> larger size (vol_scale = target/realized > 1); higher vol -> smaller.
    assert low_vol.quantity.as_double() > high_vol.quantity.as_double()


def test_close_position_releases_budget_for_next_evaluate(instrument) -> None:
    engine = RiskEngine(
        RiskConfig(risk_per_trade=0.1, max_portfolio_risk=0.1, max_concurrent_positions=5)
    )
    engine.open_position("BTCUSDT", risk_fraction=0.1)
    blocked = engine.evaluate(instrument=instrument, price=50_000.0, equity=100_000.0, now=_now())
    assert not blocked.approved

    engine.close_position("BTCUSDT", realized_pnl=500.0, now=_now())
    freed = engine.evaluate(instrument=instrument, price=50_000.0, equity=100_500.0, now=_now())
    assert freed.approved


def test_open_position_count_tracks_state(instrument) -> None:
    engine = RiskEngine(RiskConfig())
    assert engine.open_position_count == 0
    engine.open_position("BTCUSDT", risk_fraction=0.01)
    assert engine.open_position_count == 1
    engine.close_position("BTCUSDT", realized_pnl=10.0, now=_now())
    assert engine.open_position_count == 0


def test_zero_or_negative_price_rejected(instrument) -> None:
    engine = RiskEngine(RiskConfig())
    decision = engine.evaluate(instrument=instrument, price=0.0, equity=100_000.0, now=_now())
    assert not decision.approved


def test_rejected_and_canceled_orders_release_reserved_risk(instrument) -> None:
    engine = RiskEngine(RiskConfig(max_portfolio_risk=0.1, max_concurrent_positions=5))
    engine.reserve("BTC", 0.1)
    assert engine.reserved_risk == pytest.approx(0.1)
    engine.reject("BTC")
    assert engine.reserved_risk == 0.0
    engine.reserve("BTC", 0.1)
    engine.cancel("BTC")
    assert engine.risk_state("BTC") == "canceled"


def test_full_risk_lifecycle_state_transitions() -> None:
    engine = RiskEngine(RiskConfig(max_concurrent_positions=5))
    engine.propose("BTC")
    assert engine.risk_state("BTC") == "proposed"
    engine.mark_pending("BTC")
    assert engine.risk_state("BTC") == "pending"
    engine.reserve("BTC", 0.1)
    assert engine.risk_state("BTC") == "reserved"
    engine.apply_fill("BTC", 0.5)
    assert engine.risk_state("BTC") == "partially_filled"
    engine.apply_fill("BTC", 1.0)
    assert engine.risk_state("BTC") == "open"
    engine.begin_close("BTC")
    assert engine.risk_state("BTC") == "closing"
    engine.close_position("BTC", realized_pnl=1.0, now=_now())
    assert engine.risk_state("BTC") == "closed"


def test_partial_fill_tracks_only_real_exposure(instrument) -> None:
    engine = RiskEngine(RiskConfig(max_portfolio_risk=0.2, max_concurrent_positions=5))
    engine.reserve("BTC", 0.1)
    engine.apply_fill("BTC", 0.25)
    assert engine.risk_state("BTC") == "partially_filled"
    assert engine.reserved_risk == pytest.approx(0.075)
    assert engine.open_position_count == 1
    engine.apply_fill("BTC", 1.0)
    assert engine.risk_state("BTC") == "open"
    assert engine.reserved_risk == 0.0


def test_pending_reservation_counts_toward_concurrent_limit(instrument) -> None:
    engine = RiskEngine(RiskConfig(max_concurrent_positions=1, max_portfolio_risk=0.5))
    engine.reserve("ETH", 0.1)
    decision = engine.evaluate(
        instrument=instrument, price=50_000.0, equity=100_000.0, now=_now()
    )
    assert not decision.approved
    assert "max_concurrent_positions" in decision.reason


def test_snapshot_round_trip_preserves_partial_fill_and_daily_limits(instrument) -> None:
    config = RiskConfig(max_daily_loss=0.02, max_portfolio_risk=0.5, max_concurrent_positions=5)
    engine = RiskEngine(config)
    engine.reserve("BTC", 0.1)
    engine.apply_fill("BTC", 0.25)
    engine.open_position("ETH", 0.1)
    engine.close_position("ETH", realized_pnl=-3_000.0, now=_now())

    restored = RiskEngine.from_snapshot(config, engine.snapshot())
    assert restored.risk_state("BTC") == "partially_filled"
    assert restored.reserved_risk == pytest.approx(0.075)
    decision = restored.evaluate(
        instrument=instrument, price=50_000.0, equity=97_000.0, now=_now()
    )
    assert not decision.approved
    assert "max_daily_loss" in decision.reason


def test_reconciliation_replaces_stale_local_state() -> None:
    engine = RiskEngine(RiskConfig(max_concurrent_positions=5))
    engine.open_position("STALE", 0.1)
    engine.reserve("PENDING", 0.05)

    mismatches = engine.reconcile(
        actual_open_risk={"BTC": 0.02}, actual_reserved_risk={"ETH": 0.03}
    )

    assert mismatches == ("open_positions", "reservations")
    assert engine.risk_state("STALE") == "closed"
    assert engine.risk_state("BTC") == "open"
    assert engine.risk_state("ETH") == "reserved"
    assert engine.reserved_risk == pytest.approx(0.03)
