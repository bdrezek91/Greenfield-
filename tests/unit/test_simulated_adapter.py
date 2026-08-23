"""SimulatedExecutionAdapter must apply slippage in the adverse direction,
respect configured latency, and be reproducible with a seed.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import pytest

from src.execution.intent import IntentSide, OrderIntent
from src.execution.simulated_adapter import SimulatedAdapterConfig, SimulatedExecutionAdapter


def _intent(side: IntentSide) -> OrderIntent:
    return OrderIntent(
        symbol="BTCUSDT",
        side=side,
        quantity=1.0,
        reference_price=100.0,
        created_at=datetime(2024, 1, 1, tzinfo=UTC),
    )


def test_buy_fills_above_reference_price() -> None:
    adapter = SimulatedExecutionAdapter(SimulatedAdapterConfig(slippage_bps=10.0, seed=1))
    fill = adapter.submit(_intent(IntentSide.BUY))
    assert fill.filled_price > 100.0
    assert fill.filled_price == pytest.approx(100.1)  # 10 bps of 100


def test_sell_fills_below_reference_price() -> None:
    adapter = SimulatedExecutionAdapter(SimulatedAdapterConfig(slippage_bps=10.0, seed=1))
    fill = adapter.submit(_intent(IntentSide.SELL))
    assert fill.filled_price < 100.0
    assert fill.filled_price == pytest.approx(99.9)


def test_latency_applied_to_filled_at() -> None:
    adapter = SimulatedExecutionAdapter(SimulatedAdapterConfig(latency_seconds=0.5, seed=1))
    intent = _intent(IntentSide.BUY)
    fill = adapter.submit(intent)
    assert (fill.filled_at - intent.created_at).total_seconds() == pytest.approx(0.5)


def test_zero_reject_probability_never_rejects() -> None:
    adapter = SimulatedExecutionAdapter(SimulatedAdapterConfig(reject_probability=0.0, seed=1))
    for _ in range(50):
        assert not adapter.submit(_intent(IntentSide.BUY)).rejected


def test_full_reject_probability_always_rejects() -> None:
    adapter = SimulatedExecutionAdapter(SimulatedAdapterConfig(reject_probability=1.0, seed=1))
    fill = adapter.submit(_intent(IntentSide.BUY))
    assert fill.rejected
    assert fill.reject_reason == "simulated rejection"


def test_reproducible_with_seed() -> None:
    intent = _intent(IntentSide.BUY)
    a = SimulatedExecutionAdapter(SimulatedAdapterConfig(reject_probability=0.5, seed=42))
    b = SimulatedExecutionAdapter(SimulatedAdapterConfig(reject_probability=0.5, seed=42))
    results_a = [a.submit(intent).rejected for _ in range(20)]
    results_b = [b.submit(intent).rejected for _ in range(20)]
    assert results_a == results_b


def test_realistic_cost_components_and_partial_fill_are_recorded() -> None:
    adapter = SimulatedExecutionAdapter(
        SimulatedAdapterConfig(
            slippage_bps=4.0,
            spread_bps=6.0,
            taker_fee_bps=5.0,
            funding_bps=2.0,
            partial_fill_probability=1.0,
            minimum_fill_fraction=0.5,
            seed=7,
        )
    )

    fill = adapter.submit(_intent(IntentSide.BUY))

    assert 0.5 <= fill.filled_quantity < 1.0
    assert fill.filled_price == pytest.approx(100.07)
    assert fill.spread_cost_quote > 0
    assert fill.slippage_cost_quote > 0
    assert fill.fee_cost_quote > 0
    assert fill.funding_cost_quote > 0
    assert fill.total_cost_quote == pytest.approx(
        fill.spread_cost_quote
        + fill.slippage_cost_quote
        + fill.fee_cost_quote
        + fill.funding_cost_quote
    )


def test_latency_and_slippage_jitter_are_seeded_and_adverse() -> None:
    config = SimulatedAdapterConfig(
        latency_seconds=0.1,
        latency_jitter_seconds=0.4,
        slippage_bps=1.0,
        slippage_jitter_bps=9.0,
        seed=11,
    )
    left = SimulatedExecutionAdapter(config).submit(_intent(IntentSide.SELL))
    right = SimulatedExecutionAdapter(config).submit(_intent(IntentSide.SELL))

    assert left == right
    assert 0.1 <= (left.filled_at - left.intent.created_at).total_seconds() <= 0.5
    assert left.filled_price < left.intent.reference_price


@pytest.mark.parametrize(
    "kwargs",
    [
        {"slippage_bps": -1},
        {"reject_probability": 1.1},
        {"partial_fill_probability": -0.1},
        {"minimum_fill_fraction": 0},
    ],
)
def test_invalid_realism_config_is_rejected(kwargs: dict[str, Any]) -> None:
    with pytest.raises(ValueError):
        SimulatedAdapterConfig(**kwargs)
