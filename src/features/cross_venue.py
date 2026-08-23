"""Point-in-time cross-venue clock and price sanity snapshots."""

from __future__ import annotations

import pandas as pd

_DEFAULT_MAX_AGE = pd.Timedelta(seconds=5)


def cross_venue_snapshot(
    quotes: pd.DataFrame,
    *,
    canonical_instrument_id: str,
    as_of: pd.Timestamp,
    max_age: pd.Timedelta = _DEFAULT_MAX_AGE,
    max_deviation_bps: float = 50.0,
) -> pd.DataFrame:
    """Select the latest available quote per venue and compare with the median."""
    required = {
        "timestamp",
        "max_source_timestamp",
        "exchange",
        "canonical_instrument_id",
        "mid_price",
    }
    missing = sorted(required - set(quotes.columns))
    if missing:
        raise ValueError(f"cross-venue quotes missing columns: {missing}")
    cutoff = _utc(as_of, "as_of")
    if max_age <= pd.Timedelta(0) or max_deviation_bps <= 0:
        raise ValueError("cross-venue thresholds must be positive")
    value = quotes.copy()
    value["timestamp"] = pd.to_datetime(value["timestamp"], utc=True)
    value["max_source_timestamp"] = pd.to_datetime(
        value["max_source_timestamp"], utc=True
    )
    if (value["max_source_timestamp"] > value["timestamp"]).any():
        raise ValueError("cross-venue quote contains future source timestamp")
    value = value.loc[
        (value["canonical_instrument_id"] == canonical_instrument_id)
        & (value["timestamp"] <= cutoff)
        & (value["max_source_timestamp"] <= cutoff)
    ]
    if value.empty:
        return _empty_snapshot()
    latest = (
        value.sort_values(["exchange", "timestamp", "max_source_timestamp"])
        .groupby("exchange", as_index=False)
        .tail(1)
        .copy()
    )
    latest["quote_age_ms"] = (
        cutoff - latest["max_source_timestamp"]
    ).dt.total_seconds() * 1_000.0
    latest = latest.loc[latest["quote_age_ms"] <= max_age.total_seconds() * 1_000.0]
    if latest.empty:
        return _empty_snapshot()
    if (latest["mid_price"].astype(float) <= 0).any():
        raise ValueError("cross-venue mid prices must be positive")
    median = float(latest["mid_price"].astype(float).median())
    latest["cross_venue_median"] = median
    latest["price_deviation_bps"] = (
        latest["mid_price"].astype(float) / median - 1.0
    ) * 10_000.0
    latest["is_price_outlier"] = (
        latest["price_deviation_bps"].abs() > max_deviation_bps
    ).astype(int)
    latest["snapshot_timestamp"] = cutoff
    columns = list(_empty_snapshot().columns)
    return latest[columns].sort_values("exchange").reset_index(drop=True)


def cross_venue_series_frame(
    quotes: pd.DataFrame,
    *,
    canonical_instrument_id: str,
    as_of_timestamps: pd.Series,
    max_age: pd.Timedelta = _DEFAULT_MAX_AGE,
    max_deviation_bps: float = 50.0,
) -> pd.DataFrame:
    """Causal walk-forward wrapper around `cross_venue_snapshot`: calls it
    once per `as_of_timestamps` entry and reduces each POINT-in-time,
    one-row-per-venue snapshot down to one row of bar-level summary
    features - the same "new function to bridge the shape gap before
    wiring is possible" pattern as
    src.features.auction.rolling_volume_profile_frame (built for Cycle
    27's volume_profile extra). `cross_venue_snapshot` itself never sees
    a future quote, so this function does not either.
    """
    rows: list[dict[str, object]] = []
    for as_of in as_of_timestamps:
        snapshot = cross_venue_snapshot(
            quotes,
            canonical_instrument_id=canonical_instrument_id,
            as_of=as_of,
            max_age=max_age,
            max_deviation_bps=max_deviation_bps,
        )
        if snapshot.empty:
            rows.append(
                {
                    "timestamp": as_of,
                    "max_source_timestamp": as_of,
                    "cross_venue_count": 0,
                    "cross_venue_max_abs_deviation_bps": float("nan"),
                    "cross_venue_outlier_count": 0,
                    "cross_venue_median_price": float("nan"),
                }
            )
        else:
            rows.append(
                {
                    "timestamp": as_of,
                    "max_source_timestamp": snapshot["max_source_timestamp"].max(),
                    "cross_venue_count": len(snapshot),
                    "cross_venue_max_abs_deviation_bps": float(
                        snapshot["price_deviation_bps"].abs().max()
                    ),
                    "cross_venue_outlier_count": int(snapshot["is_price_outlier"].sum()),
                    "cross_venue_median_price": float(snapshot["cross_venue_median"].iloc[0]),
                }
            )
    return pd.DataFrame(
        rows,
        columns=[
            "timestamp",
            "max_source_timestamp",
            "cross_venue_count",
            "cross_venue_max_abs_deviation_bps",
            "cross_venue_outlier_count",
            "cross_venue_median_price",
        ],
    )


def _utc(value: pd.Timestamp, name: str) -> pd.Timestamp:
    result = pd.Timestamp(value)
    if result.tzinfo is None:
        raise ValueError(f"{name} must be timezone-aware")
    return result.tz_convert("UTC")


def _empty_snapshot() -> pd.DataFrame:
    return pd.DataFrame(
        columns=[
            "snapshot_timestamp",
            "timestamp",
            "max_source_timestamp",
            "exchange",
            "canonical_instrument_id",
            "mid_price",
            "quote_age_ms",
            "cross_venue_median",
            "price_deviation_bps",
            "is_price_outlier",
        ]
    )
