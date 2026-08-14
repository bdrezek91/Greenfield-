"""ExecutionAdapter protocol: submit an OrderIntent, get back a Fill.

Swapping the adapter (backtest / paper-on-Bybit-testnet / a future exchange)
never requires touching strategy or risk-engine code - the whole point of
separating SIGNAL/RISK from EXECUTION (section 31). See
src/execution/bybit_paper_adapter.py for the Bybit testnet implementation
and src/execution/fill_tracking.py for comparing Fills against expectations.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from src.execution.intent import OrderIntent


@dataclass(frozen=True)
class Fill:
    intent: OrderIntent
    filled_price: float
    filled_quantity: float
    filled_at: datetime
    rejected: bool = False
    reject_reason: str = ""


class ExecutionAdapter(Protocol):
    def submit(self, intent: OrderIntent) -> Fill: ...
