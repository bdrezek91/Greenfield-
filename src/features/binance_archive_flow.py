"""Causal features from normalized Binance historical trade archives."""

from __future__ import annotations

import math

import numpy as np
import pandas as pd

from src.features.auction import volume_profile
from src.features.momentum_flow import momentum_money_flow_frame

_REQUIRED_TRADES = {
    "timestamp",
    "exchange",
    "market",
    "dataset",
    "symbol",
    "price",
    "quantity",
    "quote_quantity",
    "signed_quantity",
}


def archive_trade_bars(frame: pd.DataFrame, *, frequency: str = "1min") -> pd.DataFrame:
    """Aggregate trades into causal OHLCV/order-flow bars and cumulative CVD."""
    value, interval = _validated_trades(frame, frequency=frequency)
    value["bucket"] = value["timestamp"].dt.floor(frequency)
    value["buy_volume"] = value["signed_quantity"].clip(lower=0)
    value["sell_volume"] = -value["signed_quantity"].clip(upper=0)
    keys = ["exchange", "market", "dataset", "symbol", "bucket"]
    grouped = value.groupby(keys, sort=True, observed=True)
    output = grouped.agg(
        open=("price", "first"),
        high=("price", "max"),
        low=("price", "min"),
        close=("price", "last"),
        volume=("quantity", "sum"),
        quote_volume=("quote_quantity", "sum"),
        buy_volume=("buy_volume", "sum"),
        sell_volume=("sell_volume", "sum"),
        trade_delta=("signed_quantity", "sum"),
        trade_count=("price", "size"),
        max_source_timestamp=("timestamp", "max"),
    ).reset_index()
    output["trade_vwap"] = output["quote_volume"] / output["volume"]
    output["timestamp"] = output.pop("bucket") + interval
    stream_keys = ["exchange", "market", "dataset", "symbol"]
    output["cvd"] = output.groupby(stream_keys, sort=False, observed=True)[
        "trade_delta"
    ].cumsum()
    ordered = [
        "timestamp",
        "max_source_timestamp",
        *stream_keys,
        "open",
        "high",
        "low",
        "close",
        "volume",
        "quote_volume",
        "buy_volume",
        "sell_volume",
        "trade_delta",
        "cvd",
        "trade_count",
        "trade_vwap",
    ]
    return output[ordered]


def archive_footprint(
    frame: pd.DataFrame,
    *,
    price_tick: float,
    frequency: str = "1min",
    imbalance_ratio: float = 3.0,
) -> pd.DataFrame:
    """Build an ATAS-like price-by-time footprint without proprietary code."""
    value, interval = _validated_trades(frame, frequency=frequency)
    if not math.isfinite(price_tick) or price_tick <= 0:
        raise ValueError("price_tick must be positive and finite")
    if not math.isfinite(imbalance_ratio) or imbalance_ratio <= 0:
        raise ValueError("imbalance_ratio must be positive and finite")
    identity = value[["exchange", "market", "dataset", "symbol"]].drop_duplicates()
    if len(identity) != 1:
        raise ValueError("footprint accepts exactly one exchange/market/dataset/symbol stream")
    ticks = np.rint(value["price"].to_numpy(dtype=float) / price_tick).astype(np.int64)
    reconstructed = ticks.astype(float) * price_tick
    if not np.allclose(value["price"], reconstructed, rtol=0, atol=price_tick * 1e-6):
        raise ValueError("trade price is not aligned to price_tick")
    value["bucket"] = value["timestamp"].dt.floor(frequency)
    value["price_tick"] = ticks
    value["buy_volume"] = value["signed_quantity"].clip(lower=0)
    value["sell_volume"] = -value["signed_quantity"].clip(upper=0)
    keys = ["bucket", "price_tick"]
    result = (
        value.groupby(keys, sort=True, observed=True)
        .agg(
            buy_volume=("buy_volume", "sum"),
            sell_volume=("sell_volume", "sum"),
            max_source_timestamp=("timestamp", "max"),
        )
        .reset_index()
    )
    result["price_level"] = result["price_tick"] * price_tick
    result["total_volume"] = result["buy_volume"] + result["sell_volume"]
    result["delta"] = result["buy_volume"] - result["sell_volume"]
    indexed = result.set_index(["bucket", "price_tick"])
    lower_sell = indexed["sell_volume"].reindex(
        pd.MultiIndex.from_arrays(
            [result["bucket"], result["price_tick"] - 1], names=["bucket", "price_tick"]
        ),
        fill_value=0.0,
    ).to_numpy()
    upper_buy = indexed["buy_volume"].reindex(
        pd.MultiIndex.from_arrays(
            [result["bucket"], result["price_tick"] + 1], names=["bucket", "price_tick"]
        ),
        fill_value=0.0,
    ).to_numpy()
    result["diagonal_buy_ratio"] = np.divide(
        result["buy_volume"], lower_sell, out=np.zeros(len(result)), where=lower_sell > 0
    )
    result["diagonal_sell_ratio"] = np.divide(
        result["sell_volume"], upper_buy, out=np.zeros(len(result)), where=upper_buy > 0
    )
    result["buy_imbalance"] = result["diagonal_buy_ratio"] >= imbalance_ratio
    result["sell_imbalance"] = result["diagonal_sell_ratio"] >= imbalance_ratio
    result["timestamp"] = result.pop("bucket") + interval
    for column, scalar in identity.iloc[0].items():
        result[column] = scalar
    return result[
        [
            "timestamp",
            "max_source_timestamp",
            "exchange",
            "market",
            "dataset",
            "symbol",
            "price_level",
            "buy_volume",
            "sell_volume",
            "total_volume",
            "delta",
            "diagonal_buy_ratio",
            "diagonal_sell_ratio",
            "buy_imbalance",
            "sell_imbalance",
        ]
    ]


def archive_volume_profile(
    footprint: pd.DataFrame, *, value_area_fraction: float = 0.70
) -> pd.DataFrame:
    """Compute per-bucket POC/VAH/VAL from a historical footprint."""
    required = {"timestamp", "max_source_timestamp", "price_level", "total_volume"}
    if not required.issubset(footprint.columns):
        raise ValueError(f"footprint missing columns: {sorted(required - set(footprint.columns))}")
    rows: list[dict[str, object]] = []
    for timestamp, bucket in footprint.groupby("timestamp", sort=True):
        profile = volume_profile(bucket, value_area_fraction=value_area_fraction)
        rows.append(
            {
                "timestamp": timestamp,
                "max_source_timestamp": bucket["max_source_timestamp"].max(),
                "poc": profile.poc,
                "vah": profile.vah,
                "val": profile.val,
                "profile_volume": profile.total_volume,
                "value_area_volume": profile.value_area_volume,
            }
        )
    return pd.DataFrame(rows)


def archive_mc_like_features(bars: pd.DataFrame) -> pd.DataFrame:
    """Apply Greenfield's clean-room MC-like family to historical bars."""
    identity = bars[["exchange", "market", "dataset", "symbol"]].drop_duplicates()
    if len(identity) != 1:
        raise ValueError("MC-like features accept exactly one historical stream")
    result = momentum_money_flow_frame(bars)
    for column, scalar in identity.iloc[0].items():
        result[column] = scalar
    return result


def synchronize_spot_perp_flow(bars: pd.DataFrame) -> pd.DataFrame:
    """Exact-clock spot/perpetual join; unmatched buckets are never fabricated."""
    required = {
        "timestamp",
        "max_source_timestamp",
        "exchange",
        "market",
        "symbol",
        "trade_delta",
        "cvd",
        "volume",
        "trade_vwap",
    }
    if not required.issubset(bars.columns):
        raise ValueError(f"bars missing columns: {sorted(required - set(bars.columns))}")
    if bars.duplicated(["timestamp", "exchange", "market", "symbol"]).any():
        raise ValueError("duplicate synchronized bucket identity")
    markets = set(bars["market"].astype(str))
    if not markets.issubset({"spot", "futures-um"}):
        raise ValueError("synchronization accepts Binance spot and futures-um only")
    join_keys = ["timestamp", "exchange", "symbol"]
    metrics = ["max_source_timestamp", "trade_delta", "cvd", "volume", "trade_vwap"]
    spot = bars[bars["market"] == "spot"][join_keys + metrics]
    perp = bars[bars["market"] == "futures-um"][join_keys + metrics]
    result = spot.merge(perp, on=join_keys, how="inner", suffixes=("_spot", "_perp"))
    if result.empty:
        return result
    result["max_source_timestamp"] = result[
        ["max_source_timestamp_spot", "max_source_timestamp_perp"]
    ].max(axis=1)
    result["spot_perp_delta_divergence"] = (
        result["trade_delta_spot"] - result["trade_delta_perp"]
    )
    result["spot_perp_cvd_divergence"] = result["cvd_spot"] - result["cvd_perp"]
    total_volume = result["volume_spot"] + result["volume_perp"]
    result["spot_volume_share"] = result["volume_spot"] / total_volume.replace(0, np.nan)
    result["basis_bps"] = (
        (result["trade_vwap_perp"] / result["trade_vwap_spot"] - 1.0) * 10_000.0
    )
    result["flow_agreement"] = np.sign(result["trade_delta_spot"]) == np.sign(
        result["trade_delta_perp"]
    )
    return result.sort_values(join_keys).reset_index(drop=True)


def _validated_trades(
    frame: pd.DataFrame, *, frequency: str
) -> tuple[pd.DataFrame, pd.Timedelta]:
    if not _REQUIRED_TRADES.issubset(frame.columns):
        missing = sorted(_REQUIRED_TRADES - set(frame.columns))
        raise ValueError(f"trade frame missing columns: {missing}")
    interval = pd.Timedelta(frequency)
    if interval <= pd.Timedelta(0):
        raise ValueError("frequency must be positive")
    value = frame.copy()
    value["timestamp"] = pd.to_datetime(value["timestamp"], utc=True)
    numeric = ["price", "quantity", "quote_quantity", "signed_quantity"]
    value[numeric] = value[numeric].apply(pd.to_numeric, errors="raise")
    if value.empty or (value["price"] <= 0).any() or (value["quantity"] <= 0).any():
        raise ValueError("trade frame must contain positive price and quantity")
    if not value["dataset"].isin(["trades", "aggTrades"]).all():
        raise ValueError("unsupported historical trade dataset")
    value = value.sort_values(["timestamp", "trade_id"], kind="stable").reset_index(drop=True)
    return value, interval
