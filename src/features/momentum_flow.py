"""Independent Market-Cipher-like momentum/money-flow feature family.

This is an original composition of standard EMA normalization, Wilder RSI,
and rolling positive/negative money flow.  It contains no proprietary code.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from src.features.divergence import confirmed_divergence_frame


def momentum_money_flow_frame(
    frame: pd.DataFrame,
    *,
    channel_span: int = 10,
    momentum_span: int = 21,
    signal_window: int = 4,
    money_flow_window: int = 14,
    rsi_window: int = 14,
    pivot_left: int = 2,
    pivot_right: int = 2,
) -> pd.DataFrame:
    required = {
        "timestamp",
        "max_source_timestamp",
        "high",
        "low",
        "close",
        "volume",
    }
    if not required.issubset(frame.columns):
        raise ValueError(f"momentum frame missing columns: {sorted(required - set(frame.columns))}")
    windows = (channel_span, momentum_span, signal_window, money_flow_window, rsi_window)
    if any(window <= 1 for window in windows):
        raise ValueError("momentum/money-flow windows must exceed one")
    value = frame.sort_values("timestamp").reset_index(drop=True).copy()
    typical = (value["high"] + value["low"] + value["close"]) / 3.0
    center = typical.ewm(span=channel_span, adjust=False, min_periods=channel_span).mean()
    deviation = (typical - center).abs().ewm(
        span=channel_span, adjust=False, min_periods=channel_span
    ).mean()
    normalized = (typical - center) / (0.015 * deviation.replace(0, np.nan))
    momentum = normalized.ewm(
        span=momentum_span, adjust=False, min_periods=momentum_span
    ).mean()
    signal = momentum.rolling(signal_window, min_periods=signal_window).mean()

    raw_money = typical * value["volume"].astype(float)
    direction = typical.diff()
    positive = raw_money.where(direction > 0, 0.0)
    negative = raw_money.where(direction < 0, 0.0)
    positive_sum = positive.rolling(money_flow_window, min_periods=money_flow_window).sum()
    negative_sum = negative.rolling(money_flow_window, min_periods=money_flow_window).sum()
    ratio = positive_sum / negative_sum.replace(0, np.nan)
    money_flow = ((100 - 100 / (1 + ratio)) - 50) / 50
    money_flow = money_flow.mask((negative_sum == 0) & (positive_sum > 0), 1.0)
    money_flow = money_flow.mask((positive_sum == 0) & (negative_sum > 0), -1.0)
    money_flow = money_flow.mask((positive_sum == 0) & (negative_sum == 0), 0.0)

    change = value["close"].astype(float).diff()
    gain = change.clip(lower=0).ewm(
        alpha=1 / rsi_window,
        adjust=False,
        min_periods=rsi_window,
    ).mean()
    loss = (-change.clip(upper=0)).ewm(
        alpha=1 / rsi_window, adjust=False, min_periods=rsi_window
    ).mean()
    rsi = 100 - 100 / (1 + gain / loss.replace(0, np.nan))
    rsi = rsi.mask((loss == 0) & (gain > 0), 100.0)
    rsi = rsi.mask((gain == 0) & (loss == 0), 50.0)
    output = pd.DataFrame(
        {
            "timestamp": value["timestamp"],
            "max_source_timestamp": value["max_source_timestamp"],
            "momentum_wave": momentum,
            "momentum_signal": signal,
            "momentum_histogram": momentum - signal,
            "money_flow": money_flow,
            "rsi": rsi,
            "close": value["close"].astype(float),
        }
    ).dropna()
    output = output.reset_index(drop=True)
    divergence = confirmed_divergence_frame(
        output,
        price_col="close",
        oscillator_col="momentum_wave",
        left_bars=pivot_left,
        right_bars=pivot_right,
    )
    if divergence.empty:
        return output.drop(columns="close")
    result = output.merge(
        divergence,
        on=["timestamp", "max_source_timestamp"],
        how="left",
    )
    divergence_columns = [
        column
        for column in divergence
        if column not in {"timestamp", "max_source_timestamp"}
    ]
    result[divergence_columns] = result[divergence_columns].fillna(0).astype(int)
    return result.drop(columns="close")
