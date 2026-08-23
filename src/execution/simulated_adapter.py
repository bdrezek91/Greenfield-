"""A deterministic, injectable ExecutionAdapter for testing the full
SIGNAL -> RISK -> ORDER INTENT -> EXECUTION pipeline without any network
dependency, and for DRY-RUN sessions (project brief section 1 lists
RESEARCH/BACKTEST/PAPER as valid modes - a dry-run against replayed data
uses this adapter, not the Bybit one).

Models explicit spread, adverse slippage, fees, funding, latency jitter,
partial fills, and rejections. Every stochastic path is seeded for
reproducibility and every cost component is preserved on the Fill.
"""

from __future__ import annotations

import math
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
    spread_bps: float = 0.0
    taker_fee_bps: float = 0.0
    funding_bps: float = 0.0
    partial_fill_probability: float = 0.0
    minimum_fill_fraction: float = 0.25
    latency_jitter_seconds: float = 0.0
    slippage_jitter_bps: float = 0.0
    seed: int | None = None

    def __post_init__(self) -> None:
        non_negative = (
            self.slippage_bps,
            self.latency_seconds,
            self.spread_bps,
            self.taker_fee_bps,
            self.funding_bps,
            self.latency_jitter_seconds,
            self.slippage_jitter_bps,
        )
        if any(not math.isfinite(value) or value < 0 for value in non_negative):
            raise ValueError("simulated execution costs and latency must be non-negative")
        probabilities = (self.reject_probability, self.partial_fill_probability)
        if any(not math.isfinite(value) or not 0 <= value <= 1 for value in probabilities):
            raise ValueError("simulated execution probabilities must be in [0, 1]")
        if (
            not math.isfinite(self.minimum_fill_fraction)
            or not 0 < self.minimum_fill_fraction <= 1
        ):
            raise ValueError("minimum fill fraction must be in (0, 1]")


class SimulatedExecutionAdapter:
    def __init__(self, config: SimulatedAdapterConfig | None = None) -> None:
        self.config = config or SimulatedAdapterConfig()
        self._rng = random.Random(self.config.seed)

    def submit(self, intent: OrderIntent) -> Fill:
        latency = self.config.latency_seconds
        if self.config.latency_jitter_seconds > 0:
            latency += self._rng.uniform(0.0, self.config.latency_jitter_seconds)
        filled_at = intent.created_at + timedelta(seconds=latency)

        if self._rng.random() < self.config.reject_probability:
            return Fill(
                intent=intent,
                filled_price=0.0,
                filled_quantity=0.0,
                filled_at=filled_at,
                rejected=True,
                reject_reason="simulated rejection",
            )

        fill_fraction = 1.0
        if (
            self.config.partial_fill_probability > 0
            and self._rng.random() < self.config.partial_fill_probability
        ):
            fill_fraction = self._rng.uniform(self.config.minimum_fill_fraction, 1.0)
        filled_quantity = intent.quantity * fill_fraction
        slippage_bps = self.config.slippage_bps
        if self.config.slippage_jitter_bps > 0:
            slippage_bps += self._rng.uniform(0.0, self.config.slippage_jitter_bps)
        half_spread_bps = self.config.spread_bps / 2
        execution_impact_fraction = (half_spread_bps + slippage_bps) / 10_000
        adverse_direction = 1 if intent.side == IntentSide.BUY else -1
        filled_price = intent.reference_price * (
            1 + adverse_direction * execution_impact_fraction
        )
        reference_notional = intent.reference_price * filled_quantity
        spread_cost = reference_notional * half_spread_bps / 10_000
        slippage_cost = reference_notional * slippage_bps / 10_000
        fee_cost = filled_price * filled_quantity * self.config.taker_fee_bps / 10_000
        funding_cost = reference_notional * self.config.funding_bps / 10_000

        return Fill(
            intent=intent,
            filled_price=filled_price,
            filled_quantity=filled_quantity,
            filled_at=filled_at,
            spread_cost_quote=spread_cost,
            slippage_cost_quote=slippage_cost,
            fee_cost_quote=fee_cost,
            funding_cost_quote=funding_cost,
        )
