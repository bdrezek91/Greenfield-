"""Pure, Nautilus-independent entry-signal functions shared between a
benchmark/family strategy and anything that wraps it (e.g.
src/strategies/ml_filtered.py, Phase 13) - extracted so the underlying rule
is defined exactly once and an ML filter can reuse the identical logic
rather than a re-implementation that could silently drift from it.
"""

from __future__ import annotations

from collections.abc import Sequence

from nautilus_trader.model.enums import OrderSide


def momentum_signal(
    closes: Sequence[float], lookback_bars: int, threshold: float
) -> OrderSide | None:
    """BUY/SELL if the fractional change from `closes[0]` to `closes[-1]`
    exceeds +/-`threshold`, None otherwise (including insufficient
    history). `closes` is expected to be exactly `lookback_bars + 1` long,
    oldest first - same contract as src.strategies.momentum.Momentum's
    internal deque.
    """
    if len(closes) <= lookback_bars:
        return None
    change = (closes[-1] - closes[0]) / closes[0]
    if change > threshold:
        return OrderSide.BUY
    if change < -threshold:
        return OrderSide.SELL
    return None
