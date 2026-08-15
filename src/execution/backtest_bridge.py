"""Bridge: turn a backtest's own trades into OrderIntents.

Lets the same FillTracker used for real paper/live trading be exercised and
demonstrated end to end without any network dependency: the backtest
engine's own fills become the "expected" side, and running the resulting
intents through a configured ExecutionAdapter (e.g. SimulatedExecutionAdapter
for a dry run, or eventually a live Bybit reconciliation) produces the
"actual" side to compare against - the section 32 comparison, using real
trade data from real strategies rather than synthetic/duplicated logic.
"""

from __future__ import annotations

import pandas as pd

from src.execution.intent import IntentSide, OrderIntent


def trades_to_intents(trades: pd.DataFrame, symbol: str) -> list[OrderIntent]:
    """Each closed trade's entry becomes an OrderIntent, using the
    backtest's own entry_price as the reference price the trade was
    expected to fill at.
    """
    intents = []
    for row in trades.itertuples():
        side = IntentSide.BUY if row.quantity > 0 else IntentSide.SELL
        intents.append(
            OrderIntent(
                symbol=symbol,
                side=side,
                quantity=abs(row.quantity),
                reference_price=row.entry_price,
                created_at=row.entry_time,
                reason="backtest trade replay",
            )
        )
    return intents
