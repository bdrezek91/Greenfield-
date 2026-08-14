"""ExecutionAdapter protocol: submit an OrderIntent, get back a Fill.

Swapping the adapter (backtest / paper-on-Kraken-demo / a future exchange)
never requires touching strategy or risk-engine code - the whole point of
separating SIGNAL/RISK from EXECUTION (section 31). See
src/execution/simulated_adapter.py for the deterministic offline
implementation, src/execution/kraken_adapter.py for the real Kraken
Futures implementation (via ccxt), and src/execution/fill_tracking.py for
comparing Fills against expectations.

No NautilusTrader-native live path exists for this venue (unlike the prior
Bybit configuration's src/execution/paper_node.py, removed - see
docs/PROJECT_STATUS.md's exchange migration entry: no released
nautilus_trader version ships a Kraken adapter). src/execution/
live_runner.py is what runs a strategy's signal against this Protocol
outside a NautilusTrader engine, feeding fills straight into
src/execution/fill_tracking.py's FillTracker - src/execution/
session_recorder.py's NautilusTrader-event bridge from Phase 14 isn't
needed on this path.
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
