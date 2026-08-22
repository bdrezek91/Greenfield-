"""Causal derivatives context from point-in-time aligned observations."""

from __future__ import annotations

import numpy as np
import pandas as pd


def derivatives_context_frame(
    frame: pd.DataFrame,
    *,
    rolling_window: int = 48,
    funding_periods_per_day: float = 3.0,
) -> pd.DataFrame:
    """Combine funding, OI, basis, positioning, and liquidation context.

    The input is expected to be point-in-time aligned already. The composite
    `derivatives_crowding_score` is one confirmation family, not several votes.
    """
    required = {
        "timestamp",
        "max_source_timestamp",
        "mark_price",
        "index_price",
        "open_interest",
        "funding_rate",
    }
    missing = sorted(required - set(frame.columns))
    if missing:
        raise ValueError(f"derivatives frame missing columns: {missing}")
    if rolling_window < 3 or funding_periods_per_day <= 0:
        raise ValueError("invalid derivatives feature configuration")
    value = frame.sort_values("timestamp").reset_index(drop=True).copy()
    timestamp = pd.to_datetime(value["timestamp"], utc=True)
    source_timestamp = pd.to_datetime(value["max_source_timestamp"], utc=True)
    if (source_timestamp > timestamp).any():
        raise ValueError("derivatives frame contains future source timestamps")

    mark = value["mark_price"].astype(float)
    index = value["index_price"].astype(float)
    oi = value["open_interest"].astype(float)
    funding = value["funding_rate"].astype(float)
    if (mark <= 0).any() or (index <= 0).any() or (oi < 0).any():
        raise ValueError("derivatives prices must be positive and OI non-negative")

    basis_bps = (mark / index - 1.0) * 10_000.0
    oi_change = oi.pct_change()
    mark_return = mark.pct_change()
    funding_annualized_pct = funding * funding_periods_per_day * 365.0 * 100.0
    funding_z = _rolling_zscore(funding, rolling_window)
    basis_z = _rolling_zscore(basis_bps, rolling_window)

    components = [funding_z.rename("funding"), basis_z.rename("basis")]
    long_short_ratio = _optional_positive(value, "long_short_ratio")
    if long_short_ratio is not None:
        components.append(
            _rolling_zscore(np.log(long_short_ratio), rolling_window).rename("positioning")
        )
    crowding = pd.concat(components, axis=1).mean(axis=1, skipna=False)

    long_liquidations = _optional_non_negative(value, "long_liquidation_volume")
    short_liquidations = _optional_non_negative(value, "short_liquidation_volume")
    liquidation_imbalance = pd.Series(np.nan, index=value.index, dtype=float)
    liquidation_total = pd.Series(np.nan, index=value.index, dtype=float)
    if long_liquidations is not None and short_liquidations is not None:
        liquidation_total = long_liquidations + short_liquidations
        liquidation_imbalance = (short_liquidations - long_liquidations) / (
            liquidation_total.replace(0, np.nan)
        )
        liquidation_imbalance = liquidation_imbalance.fillna(0.0)

    return pd.DataFrame(
        {
            "timestamp": timestamp,
            "max_source_timestamp": source_timestamp,
            "mark_return": mark_return,
            "oi_change": oi_change,
            "basis_bps": basis_bps,
            "funding_rate": funding,
            "funding_annualized_pct": funding_annualized_pct,
            "funding_zscore": funding_z,
            "basis_zscore": basis_z,
            "derivatives_crowding_score": crowding,
            "oi_price_confirmation": np.sign(oi_change) * np.sign(mark_return),
            "liquidation_total": liquidation_total,
            "liquidation_imbalance": liquidation_imbalance,
        }
    )


def _rolling_zscore(value: pd.Series, window: int) -> pd.Series:
    mean = value.rolling(window, min_periods=window).mean()
    standard_deviation = value.rolling(window, min_periods=window).std(ddof=0)
    return (value - mean) / standard_deviation.replace(0, np.nan)


def _optional_positive(frame: pd.DataFrame, column: str) -> pd.Series | None:
    if column not in frame:
        return None
    value = frame[column].astype(float)
    if (value <= 0).any():
        raise ValueError(f"{column} must be positive")
    return value


def _optional_non_negative(frame: pd.DataFrame, column: str) -> pd.Series | None:
    if column not in frame:
        return None
    value = frame[column].astype(float)
    if (value < 0).any():
        raise ValueError(f"{column} must be non-negative")
    return value
