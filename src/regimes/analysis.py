"""Break down strategy performance by market regime at trade entry.

Per docs/PHASE_0_ARCHITECTURE_RESEARCH.md section 13: every strategy is
analyzed separately across regimes, not just in aggregate.
"""

from __future__ import annotations

import pandas as pd

from src.analytics.metrics import TradeMetrics, compute_trade_metrics


def label_trades_with_regime(trades: pd.DataFrame, regimes: pd.DataFrame) -> pd.DataFrame:
    """Attach `trend_regime`/`vol_regime` as of each trade's `entry_time`.

    Uses an as-of backward merge: the regime label at or immediately before
    entry_time, never one computed from data after it - no lookahead across
    the trade/regime boundary. A trade entering before enough history has
    accumulated for regime classification gets `pd.NA`, not a guess.
    """
    if trades.empty:
        result = trades.copy()
        result["trend_regime"] = pd.Series(dtype="object")
        result["vol_regime"] = pd.Series(dtype="object")
        return result

    regimes_sorted = regimes.sort_values("timestamp")
    trades_sorted = trades.sort_values("entry_time").reset_index(drop=True)
    merged = pd.merge_asof(
        trades_sorted,
        regimes_sorted[["timestamp", "trend_regime", "vol_regime"]],
        left_on="entry_time",
        right_on="timestamp",
        direction="backward",
    )
    return merged.drop(columns="timestamp")


def metrics_by_regime(
    trades_with_regime: pd.DataFrame, regime_column: str
) -> dict[str, TradeMetrics]:
    """Trade-level metrics per regime bucket (e.g. one TradeMetrics per
    UPTREND/DOWNTREND/RANGE). Trades with no regime label (pd.NA - not
    enough history yet) are excluded, not silently bucketed as anything.
    """
    result: dict[str, TradeMetrics] = {}
    labeled = trades_with_regime.dropna(subset=[regime_column])
    for regime, group in labeled.groupby(regime_column, observed=True):
        result[str(regime)] = compute_trade_metrics(group)
    return result
