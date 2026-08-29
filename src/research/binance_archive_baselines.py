"""Frozen exploratory ATAS-like and MC-like event baselines for Binance Gold."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from src.data.binance_public_archive import sha256_file

SYMBOLS = ("BTCUSDT", "ETHUSDT", "SOLUSDT")
HORIZONS_MINUTES = (5, 15, 60)
OOS_START = pd.Timestamp("2026-07-16T12:00:00Z")
OOS_END = pd.Timestamp("2026-08-01T00:00:00Z")
ROUND_TRIP_COST_BPS = 12.0
ATAS_ZSCORE_WINDOW = 240
ATAS_ZSCORE_THRESHOLD = 2.0


def run_binance_archive_baselines(
    data_dir: Path,
    *,
    quality_report_path: Path,
    preregistration_path: Path,
) -> dict[str, Any]:
    quality = json.loads(Path(quality_report_path).read_text(encoding="utf-8"))
    if quality.get("period") != "2026-07" or quality.get("dataset") != "trades":
        raise ValueError("baseline requires the audited 2026-07 trades dataset")
    if quality.get("oos_ready") is not True:
        raise ValueError("baseline requires a positive OOS-ready quality report")
    results: list[dict[str, Any]] = []
    inputs: dict[str, str] = {}
    for symbol in SYMBOLS:
        root = Path(data_dir).joinpath(
            "gold/binance-public-data/v1/frequency=1min/dataset=trades",
            f"symbol={symbol}",
            "period=2026-07",
            "scope=continuous-period",
        )
        manifest = root / "manifest.json"
        inputs[symbol] = sha256_file(manifest)
        bars = pd.read_parquet(root / "futures_um_bars.parquet", columns=["timestamp", "close"])
        flow = pd.read_parquet(
            root / "spot_perp_flow.parquet",
            columns=["timestamp", "spot_perp_delta_divergence"],
        )
        mc_like = pd.read_parquet(
            root / "futures_um_mc_like.parquet",
            columns=["timestamp", "momentum_histogram", "money_flow"],
        )
        atas_signal = _atas_signal(flow)
        mc_signal = _mc_signal(mc_like)
        for family, signal in (("atas_like_order_flow_v1", atas_signal), ("mc_like_v1", mc_signal)):
            for horizon in HORIZONS_MINUTES:
                results.append(
                    {
                        "family": family,
                        "symbol": symbol,
                        "horizon_minutes": horizon,
                        **evaluate_event_signal(
                            bars,
                            signal,
                            horizon_minutes=horizon,
                            cost_bps=ROUND_TRIP_COST_BPS,
                        ),
                    }
                )
    return {
        "schema_version": 1,
        "status": "EXPLORATORY_ONLY",
        "period": "2026-07",
        "dataset": "trades",
        "frequency": "1min",
        "oos_start_utc": OOS_START.isoformat(),
        "oos_end_utc": OOS_END.isoformat(),
        "round_trip_cost_bps": ROUND_TRIP_COST_BPS,
        "horizons_minutes": list(HORIZONS_MINUTES),
        "quality_report_sha256": sha256_file(quality_report_path),
        "preregistration_sha256": sha256_file(preregistration_path),
        "gold_manifest_sha256": inputs,
        "results": results,
        "promotion_allowed": False,
    }


def evaluate_event_signal(
    bars: pd.DataFrame,
    signal: pd.DataFrame,
    *,
    horizon_minutes: int,
    cost_bps: float,
) -> dict[str, float | int | None]:
    prices = bars.copy()
    prices["timestamp"] = pd.to_datetime(prices["timestamp"], utc=True)
    prices = prices.drop_duplicates("timestamp").set_index("timestamp")["close"].astype(float)
    events = signal.copy()
    events["timestamp"] = pd.to_datetime(events["timestamp"], utc=True)
    events = events[
        events["side"].isin((-1, 1))
        & (events["timestamp"] >= OOS_START)
        & (events["timestamp"] < OOS_END)
    ].sort_values("timestamp")
    selected: list[tuple[pd.Timestamp, int, float, float]] = []
    next_eligible = OOS_START
    for event in events.itertuples(index=False):
        timestamp = pd.Timestamp(event.timestamp)
        if timestamp < next_eligible:
            continue
        entry_at = timestamp + pd.Timedelta(minutes=1)
        exit_at = entry_at + pd.Timedelta(minutes=horizon_minutes)
        if entry_at not in prices.index or exit_at not in prices.index:
            continue
        selected.append((timestamp, int(event.side), prices.loc[entry_at], prices.loc[exit_at]))
        next_eligible = exit_at
    if not selected:
        return _empty_stats()
    gross = np.asarray(
        [
            side * (exit_price / entry_price - 1.0)
            for _, side, entry_price, exit_price in selected
        ]
    )
    net = gross - cost_bps / 10_000.0
    return {
        "event_count": len(net),
        "mean_gross_bps": float(gross.mean() * 10_000.0),
        "median_gross_bps": float(np.median(gross) * 10_000.0),
        "mean_net_bps": float(net.mean() * 10_000.0),
        "median_net_bps": float(np.median(net) * 10_000.0),
        "net_win_rate": float((net > 0).mean()),
        "sequential_compound_net_return": float(np.prod(1.0 + net) - 1.0),
    }


def _atas_signal(flow: pd.DataFrame) -> pd.DataFrame:
    value = flow.sort_values("timestamp").reset_index(drop=True).copy()
    divergence = value["spot_perp_delta_divergence"].astype(float)
    history = divergence.shift(1).rolling(ATAS_ZSCORE_WINDOW, min_periods=ATAS_ZSCORE_WINDOW)
    zscore = (divergence - history.mean()) / history.std(ddof=0).replace(0, np.nan)
    value["side"] = np.select(
        [zscore >= ATAS_ZSCORE_THRESHOLD, zscore <= -ATAS_ZSCORE_THRESHOLD],
        [1, -1],
        default=0,
    )
    return value[["timestamp", "side"]]


def _mc_signal(mc_like: pd.DataFrame) -> pd.DataFrame:
    value = mc_like.sort_values("timestamp").reset_index(drop=True).copy()
    previous = value["momentum_histogram"].shift(1)
    current = value["momentum_histogram"]
    money_flow = value["money_flow"]
    value["side"] = np.select(
        [
            (previous <= 0) & (current > 0) & (money_flow > 0),
            (previous >= 0) & (current < 0) & (money_flow < 0),
        ],
        [1, -1],
        default=0,
    )
    return value[["timestamp", "side"]]


def _empty_stats() -> dict[str, float | int | None]:
    return {
        "event_count": 0,
        "mean_gross_bps": None,
        "median_gross_bps": None,
        "mean_net_bps": None,
        "median_net_bps": None,
        "net_win_rate": None,
        "sequential_compound_net_return": None,
    }
