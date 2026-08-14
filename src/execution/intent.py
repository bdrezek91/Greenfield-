"""OrderIntent: the boundary between signal+risk decisions and execution.

Per docs/PHASE_0_ARCHITECTURE_RESEARCH.md section 31:
SIGNAL -> RISK -> ORDER INTENT -> EXECUTION -> EXCHANGE.

An OrderIntent is exchange-agnostic and strategy-agnostic: it's the only
thing an execution adapter needs to submit an order, so the exchange (or
paper vs. live) can be swapped without touching strategy or risk code.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum


class IntentSide(StrEnum):
    BUY = "BUY"
    SELL = "SELL"


@dataclass(frozen=True)
class OrderIntent:
    symbol: str
    side: IntentSide
    quantity: float
    reference_price: float
    """The price the signal/risk decision was made against - the baseline
    expected fills are measured against for slippage (section 32)."""

    created_at: datetime
    reason: str = ""
    """Free-text audit trail, e.g. strategy name or signal description."""
