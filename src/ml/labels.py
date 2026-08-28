"""Supervised learning targets (labels) for the first-generation ML use
cases from docs/PHASE_0_ARCHITECTURE_RESEARCH.md section 22: setup scoring,
regime classification, expected return, expected R, volatility prediction -
never next-candle price prediction.

IMPORTANT: labels are allowed - by definition - to look forward in time
(that's what makes them a supervised target rather than a feature). This is
NOT a lookahead bug. What must never happen is a label leaking into a
FEATURE at the same row, or a label's forward window overlapping into the
evaluation window during cross-validation without purging - see
src/ml/splits.py for the purged/embargoed split that prevents the latter.

Every label function also returns the label's END timestamp per row
(`label_end_time`), which src.ml.splits.purged_kfold_split needs to detect
and remove training rows whose label window overlaps a test window.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd


@dataclass(frozen=True, slots=True)
class TripleBarrierOutcome:
    label: int
    label_end_time: pd.Timestamp
    exit_price: float
    gross_return: float
    barrier: str


def forward_return_label(df: pd.DataFrame, horizon_bars: int) -> pd.DataFrame:
    """Forward fractional return from this row's close to the close
    `horizon_bars` ahead. Returns a DataFrame with `label` and
    `label_end_time` (NaT/NaN for rows too close to the end of the data to
    have a full forward window).
    """
    future_close = df["close"].shift(-horizon_bars)
    label = future_close / df["close"] - 1
    label_end_time = df["timestamp"].shift(-horizon_bars) if "timestamp" in df.columns else None
    return pd.DataFrame({"label": label, "label_end_time": label_end_time})


def direction_label(df: pd.DataFrame, horizon_bars: int, threshold: float = 0.0) -> pd.DataFrame:
    """Three-class direction target: 1 (up), -1 (down), 0 (flat), based on
    whether the forward return exceeds +/-`threshold`. Same `label_end_time`
    semantics as forward_return_label.
    """
    forward = forward_return_label(df, horizon_bars)
    direction = pd.Series(0, index=df.index, dtype="float64")
    direction[forward["label"] > threshold] = 1.0
    direction[forward["label"] < -threshold] = -1.0
    direction[forward["label"].isna()] = float("nan")
    return pd.DataFrame({"label": direction, "label_end_time": forward["label_end_time"]})


def expected_r_label(
    df: pd.DataFrame, horizon_bars: int, atr: pd.Series, atr_multiple: float = 1.0
) -> pd.DataFrame:
    """Forward move expressed in units of risk (R), where 1R = `atr_multiple`
    x this row's ATR - a simple, ATR-based stand-in for "risk" absent a
    strategy-specific stop distance. R = forward_price_change / (atr_multiple * ATR).
    """
    future_close = df["close"].shift(-horizon_bars)
    price_change = future_close - df["close"]
    risk_unit = atr_multiple * atr
    r_multiple = price_change / risk_unit
    label_end_time = df["timestamp"].shift(-horizon_bars) if "timestamp" in df.columns else None
    return pd.DataFrame({"label": r_multiple, "label_end_time": label_end_time})


def triple_barrier_outcome(
    df: pd.DataFrame,
    *,
    index: int,
    side: int,
    atr: float,
    horizon_bars: int,
    profit_take_atr: float = 2.0,
    stop_loss_atr: float = 1.0,
    label_cost_return: float = 0.0,
) -> TripleBarrierOutcome:
    """Resolve one causal-at-entry, path-dependent triple-barrier outcome.

    The future path is label-only information. If profit and stop levels are
    both touched inside one OHLC bar, the stop wins (conservative ordering).
    """
    required = {"timestamp", "high", "low", "close"}
    missing = required - set(df.columns)
    if missing:
        raise ValueError(f"triple barrier frame missing columns: {sorted(missing)}")
    if side not in {-1, 1}:
        raise ValueError("side must be -1 or 1")
    if index < 0 or index >= len(df):
        raise IndexError("index outside triple barrier frame")
    if horizon_bars < 1 or index + horizon_bars >= len(df):
        raise ValueError("triple barrier requires a complete positive horizon")
    if not np.isfinite(atr) or atr <= 0:
        raise ValueError("atr must be finite and positive")
    if profit_take_atr <= 0 or stop_loss_atr <= 0 or label_cost_return < 0:
        raise ValueError("barrier multiples must be positive and label cost non-negative")

    entry = float(df.iloc[index]["close"])
    if not np.isfinite(entry) or entry <= 0:
        raise ValueError("entry close must be finite and positive")
    profit_price = entry + side * profit_take_atr * atr
    stop_price = entry - side * stop_loss_atr * atr
    if min(profit_price, stop_price) <= 0:
        raise ValueError("barrier price must remain positive")

    exit_index = index + horizon_bars
    exit_price = float(df.iloc[exit_index]["close"])
    barrier = "VERTICAL"
    for future_index in range(index + 1, exit_index + 1):
        high = float(df.iloc[future_index]["high"])
        low = float(df.iloc[future_index]["low"])
        stop_hit = low <= stop_price if side == 1 else high >= stop_price
        profit_hit = high >= profit_price if side == 1 else low <= profit_price
        if stop_hit:
            exit_index = future_index
            exit_price = stop_price
            barrier = "STOP_LOSS"
            break
        if profit_hit:
            exit_index = future_index
            exit_price = profit_price
            barrier = "PROFIT_TAKE"
            break

    gross_return = side * (exit_price / entry - 1.0)
    return TripleBarrierOutcome(
        label=int(gross_return - label_cost_return > 0),
        label_end_time=pd.Timestamp(df.iloc[exit_index]["timestamp"]),
        exit_price=exit_price,
        gross_return=gross_return,
        barrier=barrier,
    )
