"""ExecutionAdapter protocol: submit an OrderIntent, get back a Fill.

Swapping the adapter (backtest / paper-on-Bybit-testnet / a future exchange)
never requires touching strategy or risk-engine code - the whole point of
separating SIGNAL/RISK from EXECUTION (section 31). See
src/execution/simulated_adapter.py for the deterministic offline
implementation and src/execution/fill_tracking.py for comparing Fills
against expectations. The live Bybit-testnet path
(src/execution/paper_node.py) runs NautilusTrader Strategy classes
directly against NautilusTrader's own Bybit adapter rather than through
this Protocol; src/execution/session_recorder.py (Phase 14) is what
bridges that live path's OrderFilled/OrderRejected events back into
src/execution/fill_tracking.py's FillTracker.
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
    spread_cost_quote: float = 0.0
    slippage_cost_quote: float = 0.0
    fee_cost_quote: float = 0.0
    funding_cost_quote: float = 0.0
    # Durable execution identifier for this exact fill event (e.g. the
    # exchange's trade/execution id). Optional here because most Fill
    # producers (deterministic backtest, SimulatedExecutionAdapter) have no
    # restart-durability concern; src.execution.paper_reconciliation.
    # PaperOrderStore requires it to be non-empty for any non-rejected fill,
    # since it is the sole key used to detect a redelivered fill after a
    # crash and refuse to double-apply it.
    fill_id: str = ""

    @property
    def total_cost_quote(self) -> float:
        return (
            self.spread_cost_quote
            + self.slippage_cost_quote
            + self.fee_cost_quote
            + self.funding_cost_quote
        )


class ExecutionAdapter(Protocol):
    def submit(self, intent: OrderIntent) -> Fill: ...
