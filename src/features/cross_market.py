"""Causal BTC/ETH/SOL relative-strength and lead-lag context."""

from __future__ import annotations

import numpy as np
import pandas as pd


def cross_market_context_frame(
    frame: pd.DataFrame,
    *,
    benchmark_asset: str = "BTC",
    rolling_window: int = 48,
) -> pd.DataFrame:
    """Build a synchronized point-in-time cross-asset context panel.

    Each timestamp must contain one observation for every asset. Failing closed
    on incomplete panels prevents a later-arriving asset from being silently
    compared with a stale benchmark observation.
    """
    required = {
        "timestamp",
        "max_source_timestamp",
        "asset",
        "spot_price",
        "perpetual_price",
    }
    missing = sorted(required - set(frame.columns))
    if missing:
        raise ValueError(f"cross-market frame missing columns: {missing}")
    if rolling_window < 3:
        raise ValueError("cross-market rolling window must be at least 3")
    if frame.empty:
        return _empty_context()

    value = frame.copy()
    value["timestamp"] = pd.to_datetime(value["timestamp"], utc=True)
    value["max_source_timestamp"] = pd.to_datetime(value["max_source_timestamp"], utc=True)
    value["asset"] = value["asset"].astype(str).str.upper()
    if (value["max_source_timestamp"] > value["timestamp"]).any():
        raise ValueError("cross-market frame contains future source timestamps")
    if value.duplicated(["timestamp", "asset"]).any():
        raise ValueError("cross-market frame contains duplicate asset timestamps")
    if (value[["spot_price", "perpetual_price"]].astype(float) <= 0).any().any():
        raise ValueError("cross-market prices must be positive")

    benchmark = benchmark_asset.upper()
    assets = sorted(value["asset"].unique())
    if benchmark not in assets:
        raise ValueError("cross-market benchmark is absent")
    if len(assets) < 2:
        raise ValueError("cross-market context requires at least two assets")

    spot = _complete_panel(value, "spot_price", assets).astype(float)
    perpetual = _complete_panel(value, "perpetual_price", assets).astype(float)
    sources = _complete_panel(value, "max_source_timestamp", assets)
    returns = spot.pct_change(fill_method=None)
    benchmark_returns = returns[benchmark]
    log_spot = np.log(spot)
    trailing_relative_strength = log_spot.diff(rolling_window).sub(
        log_spot[benchmark].diff(rolling_window), axis=0
    )
    basis_bps = (perpetual / spot - 1.0) * 10_000.0
    return_rank = returns.rank(axis=1, method="average", pct=True)
    complete_returns = returns.notna().all(axis=1)
    breadth = returns.gt(0).mean(axis=1).where(complete_returns)
    dispersion = returns.std(axis=1, ddof=0).where(complete_returns)
    panel_source = sources.max(axis=1)

    rows: list[pd.DataFrame] = []
    for asset in assets:
        asset_returns = returns[asset]
        correlation = asset_returns.rolling(rolling_window, min_periods=rolling_window).corr(
            benchmark_returns
        )
        benchmark_lead_correlation = asset_returns.rolling(
            rolling_window, min_periods=rolling_window
        ).corr(benchmark_returns.shift(1))
        rows.append(
            pd.DataFrame(
                {
                    "timestamp": spot.index,
                    "max_source_timestamp": panel_source,
                    "asset": asset,
                    "spot_return": asset_returns,
                    "benchmark_return": benchmark_returns,
                    "spot_perpetual_basis_bps": basis_bps[asset],
                    "relative_strength_log_return": trailing_relative_strength[asset],
                    "cross_sectional_return_rank": return_rank[asset],
                    "market_breadth_positive_fraction": breadth,
                    "cross_asset_return_dispersion": dispersion,
                    "benchmark_rolling_correlation": correlation,
                    "benchmark_lead_correlation": benchmark_lead_correlation,
                }
            )
        )
    return (
        pd.concat(rows, ignore_index=True)
        .sort_values(["timestamp", "asset"])
        .reset_index(drop=True)
    )


def _complete_panel(frame: pd.DataFrame, column: str, assets: list[str]) -> pd.DataFrame:
    panel = frame.pivot(index="timestamp", columns="asset", values=column).sort_index()
    panel = panel.reindex(columns=assets)
    if panel.isna().any().any():
        raise ValueError("cross-market panel is incomplete")
    return panel


def _empty_context() -> pd.DataFrame:
    return pd.DataFrame(
        columns=[
            "timestamp",
            "max_source_timestamp",
            "asset",
            "spot_return",
            "benchmark_return",
            "spot_perpetual_basis_bps",
            "relative_strength_log_return",
            "cross_sectional_return_rank",
            "market_breadth_positive_fraction",
            "cross_asset_return_dispersion",
            "benchmark_rolling_correlation",
            "benchmark_lead_correlation",
        ]
    )
