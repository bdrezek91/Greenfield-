"""Causal divergence evidence using delayed, confirmed pivots."""

from __future__ import annotations

import pandas as pd

_OUTPUT_COLUMNS = (
    "timestamp",
    "max_source_timestamp",
    "regular_bullish_divergence",
    "hidden_bullish_divergence",
    "regular_bearish_divergence",
    "hidden_bearish_divergence",
    "confirmed_pivot_low",
    "confirmed_pivot_high",
    "pivot_age_bars",
)


def confirmed_divergence_frame(
    frame: pd.DataFrame,
    *,
    price_col: str,
    oscillator_col: str,
    left_bars: int = 2,
    right_bars: int = 2,
) -> pd.DataFrame:
    """Emit regular/hidden divergence only when a pivot is fully confirmed."""
    if left_bars <= 0 or right_bars <= 0:
        raise ValueError("pivot confirmation windows must be positive")
    required = {"timestamp", "max_source_timestamp", price_col, oscillator_col}
    if not required.issubset(frame.columns):
        missing = sorted(required - set(frame.columns))
        raise ValueError(f"divergence frame missing columns: {missing}")
    ordered = frame.sort_values("timestamp").reset_index(drop=True)
    prices = ordered[price_col].astype(float)
    oscillator = ordered[oscillator_col].astype(float)
    previous_low: tuple[float, float] | None = None
    previous_high: tuple[float, float] | None = None
    output = []
    for confirmation in range(left_bars + right_bars, len(ordered)):
        pivot = confirmation - right_bars
        window = slice(pivot - left_bars, pivot + right_bars + 1)
        price = float(prices.iloc[pivot])
        osc = float(oscillator.iloc[pivot])
        low = price == float(prices.iloc[window].min()) and (
            prices.iloc[window] == price
        ).sum() == 1
        high = price == float(prices.iloc[window].max()) and (
            prices.iloc[window] == price
        ).sum() == 1
        regular_bullish = hidden_bullish = regular_bearish = hidden_bearish = 0
        if low:
            if previous_low is not None:
                previous_price, previous_osc = previous_low
                regular_bullish = int(price < previous_price and osc > previous_osc)
                hidden_bullish = int(price > previous_price and osc < previous_osc)
            previous_low = (price, osc)
        if high:
            if previous_high is not None:
                previous_price, previous_osc = previous_high
                regular_bearish = int(price > previous_price and osc < previous_osc)
                hidden_bearish = int(price < previous_price and osc > previous_osc)
            previous_high = (price, osc)
        output.append(
            {
                "timestamp": ordered.loc[confirmation, "timestamp"],
                "max_source_timestamp": ordered.loc[confirmation, "max_source_timestamp"],
                "regular_bullish_divergence": regular_bullish,
                "hidden_bullish_divergence": hidden_bullish,
                "regular_bearish_divergence": regular_bearish,
                "hidden_bearish_divergence": hidden_bearish,
                "confirmed_pivot_low": int(low),
                "confirmed_pivot_high": int(high),
                "pivot_age_bars": right_bars,
            }
        )
    return pd.DataFrame(output, columns=_OUTPUT_COLUMNS)


def price_cvd_divergence_frame(
    trade_flow: pd.DataFrame,
    *,
    price_col: str = "trade_vwap",
    left_bars: int = 2,
    right_bars: int = 2,
) -> pd.DataFrame:
    """Build an explicitly named price/CVD confirmation family."""
    evidence = confirmed_divergence_frame(
        trade_flow,
        price_col=price_col,
        oscillator_col="cvd",
        left_bars=left_bars,
        right_bars=right_bars,
    )
    return evidence.rename(
        columns={
            "regular_bullish_divergence": "cvd_regular_bullish_divergence",
            "hidden_bullish_divergence": "cvd_hidden_bullish_divergence",
            "regular_bearish_divergence": "cvd_regular_bearish_divergence",
            "hidden_bearish_divergence": "cvd_hidden_bearish_divergence",
            "confirmed_pivot_low": "cvd_confirmed_price_pivot_low",
            "confirmed_pivot_high": "cvd_confirmed_price_pivot_high",
            "pivot_age_bars": "cvd_pivot_age_bars",
        }
    )
