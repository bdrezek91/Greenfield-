"""Assemble the input frame src.regimes.multidomain.classify_multidomain_regimes
requires from the raw feature frames this project already builds -
classify_multidomain_regimes and stabilize_regime_labels were fully
built and tested but had zero callers anywhere (found by an autonomous
survey), the same "built but unreachable" situation Cycles 26-36 closed
for src/features/. Unlike those, this one needs no NEW upstream
computation - every required column already exists somewhere in this
project's feature layer, just under different names or nested one level
away:

  - `spread_bps`/`depth_notional`: derived from
    src.features.order_flow.l2_imbalance_frame's raw `spread`/`mid_price`/
    `bid_depth`/`ask_depth` (spread converted from absolute price units to
    basis points; depth converted from base-currency size to quote-
    currency notional via mid_price).
  - `signed_delta`: src.features.order_flow.trade_flow_frame's own
    `trade_delta` (buy_volume - sell_volume) under this module's name for
    it.
  - `open_interest`: the same raw timestamp+open_interest frame
    src.data.storage.read_open_interest already produces (also what
    src.features.pipeline's `open_interest` extra as-of joins).
  - `liquidation_total`, `market_breadth_positive_fraction`,
    `cross_asset_return_dispersion`, `benchmark_return`: already present,
    unchanged, in src.features.derivatives.derivatives_context_frame's
    and src.features.cross_market.cross_market_context_frame's own
    OUTPUT (the caller passes the already-computed frame, exactly as
    src.features.pipeline's `derivatives_context`/`cross_market_context`
    extras require).
  - `realized_volatility`: computed here directly from `df` via
    src.regimes.indicators.realized_volatility (same function
    src.features.volatility already re-exports and
    src.features.pipeline's `out["realized_vol"]` already uses).

Every source above is as-of joined to `df`'s own bar timestamps - never
a future reading - the same causal contract as
src.features.pipeline._as_of_join.
"""

from __future__ import annotations

import pandas as pd

from src.regimes.indicators import realized_volatility
from src.regimes.multidomain import MultiDomainRegimeConfig, classify_multidomain_regimes


def assemble_multidomain_regime_frame(
    df: pd.DataFrame,
    *,
    l2_imbalance: pd.DataFrame,
    trade_flow: pd.DataFrame,
    open_interest: pd.DataFrame,
    derivatives_context: pd.DataFrame,
    cross_market_context: pd.DataFrame,
    volatility_period: int = 20,
) -> pd.DataFrame:
    """Build classify_multidomain_regimes's exact required input schema
    from already-computed source frames, then classify it. `df` needs
    timestamp/high/low/close; every other argument is a pre-computed
    frame the caller builds (not computed here), matching how
    src.features.pipeline.build_feature_matrix's extras work.
    """
    required_df_columns = {"timestamp", "high", "low", "close"}
    missing = sorted(required_df_columns - set(df.columns))
    if missing:
        raise ValueError(f"multidomain bridge input frame missing columns: {missing}")

    out = pd.DataFrame(
        {
            "timestamp": df["timestamp"],
            "max_source_timestamp": df["timestamp"],
            "high": df["high"],
            "low": df["low"],
            "close": df["close"],
        }
    )
    out["realized_volatility"] = realized_volatility(df, volatility_period)

    spread = _as_of_join(df["timestamp"], l2_imbalance, "spread")
    mid_price = _as_of_join(df["timestamp"], l2_imbalance, "mid_price")
    bid_depth = _as_of_join(df["timestamp"], l2_imbalance, "bid_depth")
    ask_depth = _as_of_join(df["timestamp"], l2_imbalance, "ask_depth")
    out["spread_bps"] = (spread / mid_price) * 10_000.0
    out["depth_notional"] = (bid_depth + ask_depth) * mid_price

    out["signed_delta"] = _as_of_join(df["timestamp"], trade_flow, "trade_delta")
    out["open_interest"] = _as_of_join(df["timestamp"], open_interest, "open_interest")
    out["liquidation_total"] = _as_of_join(
        df["timestamp"], derivatives_context, "liquidation_total"
    )
    for column in (
        "market_breadth_positive_fraction",
        "cross_asset_return_dispersion",
        "benchmark_return",
    ):
        out[column] = _as_of_join(df["timestamp"], cross_market_context, column)

    return out


def classify_multidomain_regimes_from_sources(
    df: pd.DataFrame,
    *,
    l2_imbalance: pd.DataFrame,
    trade_flow: pd.DataFrame,
    open_interest: pd.DataFrame,
    derivatives_context: pd.DataFrame,
    cross_market_context: pd.DataFrame,
    volatility_period: int = 20,
    config: MultiDomainRegimeConfig | None = None,
) -> pd.DataFrame:
    """assemble_multidomain_regime_frame + classify_multidomain_regimes in
    one call - the single entry point a strategy or research script needs.

    classify_multidomain_regimes fails closed on ANY non-finite value in
    its required columns (not just the row being classified) - so `df`
    must already be trimmed to a range where every source has fully
    warmed up (e.g. drop the leading `volatility_period` rows before
    realized_volatility is finite, and however many rows each source
    frame's own rolling windows need). This function does NOT trim for
    you: a leading NaN caused by mechanical warmup and one caused by a
    genuine upstream data gap look identical in the assembled frame, and
    guessing which one it is would violate classify_multidomain_regimes's
    own "never guess" contract. Slice `df` (and pass correspondingly
    sliced source frames) to a window you know is fully warmed up.
    """
    frame = assemble_multidomain_regime_frame(
        df,
        l2_imbalance=l2_imbalance,
        trade_flow=trade_flow,
        open_interest=open_interest,
        derivatives_context=derivatives_context,
        cross_market_context=cross_market_context,
        volatility_period=volatility_period,
    )
    return classify_multidomain_regimes(frame, config)


def _as_of_join(timestamps: pd.Series, source: pd.DataFrame, value_col: str) -> pd.Series:
    """Point-in-time as-of join: for each bar timestamp, the most recent
    `value_col` reading at or before it (never a future one) - same
    contract as src.features.pipeline._as_of_join.
    """
    left = pd.DataFrame({"timestamp": timestamps}).sort_values("timestamp")
    right = source[["timestamp", value_col]].sort_values("timestamp")
    merged = pd.merge_asof(left, right, on="timestamp", direction="backward")
    return merged.set_index(left.index)[value_col].reindex(timestamps.index)
