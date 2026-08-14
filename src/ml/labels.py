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

import pandas as pd


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
