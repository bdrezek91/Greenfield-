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
EXECUTION_COST_SCENARIOS = {
    "maker_maker": {
        "fee_bps": 4.0,
        "execution_buffer_bps": 2.0,
        "round_trip_cost_bps": 6.0,
    },
    "maker_taker": {
        "fee_bps": 7.5,
        "execution_buffer_bps": 1.5,
        "round_trip_cost_bps": 9.0,
    },
    "taker_taker": {
        "fee_bps": 11.0,
        "execution_buffer_bps": 2.0,
        "round_trip_cost_bps": 13.0,
    },
}
POST_ONLY_EXECUTION_SENSITIVITY = {
    "short_timeout_low_fill": {
        "timeout_seconds": 5,
        "full_fill_probability": 0.20,
        "partial_fill_probability": 0.10,
        "partial_fill_fraction": 0.50,
        "adverse_selection_bps": 3.0,
    },
    "base_timeout_medium_fill": {
        "timeout_seconds": 20,
        "full_fill_probability": 0.45,
        "partial_fill_probability": 0.15,
        "partial_fill_fraction": 0.50,
        "adverse_selection_bps": 2.0,
    },
    "long_timeout_high_fill": {
        "timeout_seconds": 60,
        "full_fill_probability": 0.70,
        "partial_fill_probability": 0.15,
        "partial_fill_fraction": 0.50,
        "adverse_selection_bps": 1.0,
    },
}
ATAS_ZSCORE_WINDOW = 240
ATAS_ZSCORE_THRESHOLD = 2.0


def run_binance_archive_baselines(
    data_dir: Path,
    *,
    quality_report_path: Path,
    preregistration_path: Path,
    period: str = "2026-07",
) -> dict[str, Any]:
    quality = json.loads(Path(quality_report_path).read_text(encoding="utf-8"))
    if quality.get("period") != period or quality.get("dataset") != "trades":
        raise ValueError(f"baseline requires the audited {period} trades dataset")
    if quality.get("oos_ready") is not True:
        raise ValueError("baseline requires a positive OOS-ready quality report")
    results: list[dict[str, Any]] = []
    inputs: dict[str, str] = {}
    oos_start, oos_end = monthly_oos_bounds(period)
    for symbol in SYMBOLS:
        root = Path(data_dir).joinpath(
            "gold/binance-public-data/v1/frequency=1min/dataset=trades",
            f"symbol={symbol}",
            f"period={period}",
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
                            oos_start=oos_start,
                            oos_end=oos_end,
                        ),
                    }
                )
    return {
        "schema_version": 3,
        "status": "EXPLORATORY_ONLY",
        "period": period,
        "dataset": "trades",
        "frequency": "1min",
        "oos_start_utc": oos_start.isoformat(),
        "oos_end_utc": oos_end.isoformat(),
        "round_trip_cost_bps": ROUND_TRIP_COST_BPS,
        "execution_cost_scenarios": EXECUTION_COST_SCENARIOS,
        "post_only_execution_sensitivity": POST_ONLY_EXECUTION_SENSITIVITY,
        "maker_fill_probability_mode": "SENSITIVITY_ONLY_NOT_EMPIRICALLY_CALIBRATED",
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
    oos_start: pd.Timestamp = OOS_START,
    oos_end: pd.Timestamp = OOS_END,
) -> dict[str, Any]:
    prices = bars.copy()
    prices["timestamp"] = pd.to_datetime(prices["timestamp"], utc=True)
    prices = prices.drop_duplicates("timestamp").set_index("timestamp")["close"].astype(float)
    events = signal.copy()
    events["timestamp"] = pd.to_datetime(events["timestamp"], utc=True)
    events = events[
        events["side"].isin((-1, 1))
        & (events["timestamp"] >= oos_start)
        & (events["timestamp"] < oos_end)
    ].sort_values("timestamp")
    selected: list[tuple[pd.Timestamp, int, float, float]] = []
    next_eligible = oos_start
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
        "execution_scenarios": {
            name: _net_stats(gross, values["round_trip_cost_bps"])
            for name, values in EXECUTION_COST_SCENARIOS.items()
        },
        "post_only_sensitivity": {
            name: _post_only_stats(gross, values)
            for name, values in POST_ONLY_EXECUTION_SENSITIVITY.items()
        },
    }


def _net_stats(gross: np.ndarray, cost_bps: float) -> dict[str, float]:
    net = gross - cost_bps / 10_000.0
    return {
        "round_trip_cost_bps": cost_bps,
        "mean_net_bps": float(net.mean() * 10_000.0),
        "median_net_bps": float(np.median(net) * 10_000.0),
        "net_win_rate": float((net > 0).mean()),
        "sequential_compound_net_return": float(np.prod(1.0 + net) - 1.0),
    }


def _post_only_stats(gross: np.ndarray, assumptions: dict[str, float]) -> dict[str, Any]:
    full_probability = assumptions["full_fill_probability"]
    partial_probability = assumptions["partial_fill_probability"]
    partial_fraction = assumptions["partial_fill_fraction"]
    if full_probability + partial_probability > 1:
        raise ValueError("PostOnly full and partial fill probabilities cannot exceed one")
    expected_fraction = full_probability + partial_probability * partial_fraction
    exit_scenarios = {
        "maker_exit": _post_only_expected_stats(
            gross,
            expected_fraction=expected_fraction,
            round_trip_cost_bps=EXECUTION_COST_SCENARIOS["maker_maker"][
                "round_trip_cost_bps"
            ],
            adverse_selection_bps=assumptions["adverse_selection_bps"],
        ),
        "taker_exit": _post_only_expected_stats(
            gross,
            expected_fraction=expected_fraction,
            round_trip_cost_bps=EXECUTION_COST_SCENARIOS["maker_taker"][
                "round_trip_cost_bps"
            ],
            adverse_selection_bps=assumptions["adverse_selection_bps"],
        ),
    }
    primary = exit_scenarios["taker_exit"]
    return {
        "timeout_seconds": assumptions["timeout_seconds"],
        "entry_mode": "POST_ONLY_MAKER",
        "primary_exit_mode": "TAKER",
        "any_fill_probability": full_probability + partial_probability,
        "expected_executed_fraction": expected_fraction,
        "miss_probability": 1 - full_probability - partial_probability,
        **primary,
        "exit_execution_scenarios": exit_scenarios,
    }


def _post_only_expected_stats(
    gross: np.ndarray,
    *,
    expected_fraction: float,
    round_trip_cost_bps: float,
    adverse_selection_bps: float,
) -> dict[str, float]:
    filled_net = gross - (round_trip_cost_bps + adverse_selection_bps) / 10_000.0
    expected_net = filled_net * expected_fraction
    return {
        "round_trip_cost_bps": round_trip_cost_bps,
        "mean_expected_net_bps_per_opportunity": float(expected_net.mean() * 10_000.0),
        "median_expected_net_bps_per_opportunity": float(np.median(expected_net) * 10_000.0),
        "positive_expected_opportunity_fraction": float((expected_net > 0).mean()),
    }


def monthly_oos_bounds(period: str) -> tuple[pd.Timestamp, pd.Timestamp]:
    """Return the fixed second-half OOS window for a closed YYYY-MM period."""
    try:
        start = pd.Timestamp(f"{period}-01T00:00:00Z")
    except ValueError as exc:
        raise ValueError(f"invalid monthly period: {period}") from exc
    if start.strftime("%Y-%m") != period:
        raise ValueError(f"invalid monthly period: {period}")
    end = start + pd.offsets.MonthBegin(1)
    midpoint = start + (end - start) / 2
    return midpoint, end


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


def _empty_stats() -> dict[str, Any]:
    return {
        "event_count": 0,
        "mean_gross_bps": None,
        "median_gross_bps": None,
        "mean_net_bps": None,
        "median_net_bps": None,
        "net_win_rate": None,
        "sequential_compound_net_return": None,
        "execution_scenarios": {
            name: {
                "round_trip_cost_bps": values["round_trip_cost_bps"],
                "mean_net_bps": None,
                "median_net_bps": None,
                "net_win_rate": None,
                "sequential_compound_net_return": None,
            }
            for name, values in EXECUTION_COST_SCENARIOS.items()
        },
        "post_only_sensitivity": {
            name: {
                "timeout_seconds": values["timeout_seconds"],
                "entry_mode": "POST_ONLY_MAKER",
                "primary_exit_mode": "TAKER",
                "any_fill_probability": values["full_fill_probability"]
                + values["partial_fill_probability"],
                "expected_executed_fraction": values["full_fill_probability"]
                + values["partial_fill_probability"] * values["partial_fill_fraction"],
                "miss_probability": 1
                - values["full_fill_probability"]
                - values["partial_fill_probability"],
                "mean_expected_net_bps_per_opportunity": None,
                "median_expected_net_bps_per_opportunity": None,
                "positive_expected_opportunity_fraction": None,
                "exit_execution_scenarios": {
                    exit_name: {
                        "round_trip_cost_bps": EXECUTION_COST_SCENARIOS[cost_name][
                            "round_trip_cost_bps"
                        ],
                        "mean_expected_net_bps_per_opportunity": None,
                        "median_expected_net_bps_per_opportunity": None,
                        "positive_expected_opportunity_fraction": None,
                    }
                    for exit_name, cost_name in (
                        ("maker_exit", "maker_maker"),
                        ("taker_exit", "maker_taker"),
                    )
                },
            }
            for name, values in POST_ONLY_EXECUTION_SENSITIVITY.items()
        },
    }
