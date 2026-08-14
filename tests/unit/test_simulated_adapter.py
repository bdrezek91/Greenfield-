"""SimulatedExecutionAdapter must apply slippage in the adverse direction,
respect configured latency, and be reproducible with a seed.
"""

from __future__ import annotations

from datetime import UTC, datetime

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
