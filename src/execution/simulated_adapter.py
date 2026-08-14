"""A deterministic, injectable ExecutionAdapter for testing the full
SIGNAL -> RISK -> ORDER INTENT -> EXECUTION pipeline without any network
dependency, and for DRY-RUN sessions (project brief section 1 lists
RESEARCH/BACKTEST/PAPER as valid modes - a dry-run against replayed data
uses this adapter, not the Bybit one).

Models a configurable, fixed one-tick-style slippage and latency, and can
be configured to reject a fraction of orders (to exercise rejection
handling) - all seeded for reproducibility.
"""

from __future__ import annotations

import random
from dataclasses import dataclass
from datetime import timedelta

from src.execution.adapter import Fill
from src.execution.intent import IntentSide, OrderIntent


@dataclass(frozen=True)
class SimulatedAdapterConfig:
    slippage_bps: float = 5.0
    """Simulated adverse slippage in basis points of the reference price."""

    latency_seconds: float = 0.2
    reject_probability: float = 0.0
    seed: int | None = None


class SimulatedExecutionAdapter:
    def __init__(self, config: SimulatedAdapterConfig | None = None) -> None:
        self.config = config or SimulatedAdapterConfig()
        self._rng = random.Random(self.config.seed)

    def submit(self, intent: OrderIntent) -> Fill:
        filled_at = intent.created_at + timedelta(seconds=self.config.latency_seconds)

        if self._rng.random() < self.config.reject_probability:
            return Fill(
                intent=intent,
                filled_price=0.0,
                filled_quantity=0.0,
                filled_at=filled_at,
                rejected=True,
                reject_reason="simulated rejection",
            )

        slippage_fraction = self.config.slippage_bps / 10_000
        adverse_direction = 1 if intent.side == IntentSide.BUY else -1
        filled_price = intent.reference_price * (1 + adverse_direction * slippage_fraction)

        return Fill(
            intent=intent,
            filled_price=filled_price,
            filled_quantity=intent.quantity,
            filled_at=filled_at,
        )
