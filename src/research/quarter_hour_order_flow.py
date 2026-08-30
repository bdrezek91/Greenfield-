"""Frozen quarter-hour opening order-flow replication baseline."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from src.data.binance_public_archive import sha256_file
from src.research.binance_archive_baselines import (
    EXECUTION_COST_SCENARIOS,
    POST_ONLY_EXECUTION_SENSITIVITY,
    SYMBOLS,
    evaluate_event_signal,
    monthly_oos_bounds,
)

HORIZONS_MINUTES = (240, 480, 720)
TRAINING_QUANTILE = 0.80


def run_quarter_hour_order_flow(
    data_dir: Path,
    *,
    quality_report_path: Path,
    preregistration_path: Path,
    period: str,
) -> dict[str, Any]:
    """Evaluate the frozen signal on one audited closed month."""
    quality = json.loads(Path(quality_report_path).read_text(encoding="utf-8"))
    if quality.get("period") != period or quality.get("dataset") != "trades":
        raise ValueError(f"baseline requires the audited {period} trades dataset")
    if quality.get("oos_ready") is not True:
        raise ValueError("baseline requires a positive OOS-ready quality report")

    oos_start, oos_end = monthly_oos_bounds(period)
    results: list[dict[str, Any]] = []
    inputs: dict[str, str] = {}
    for symbol in SYMBOLS:
        root = Path(data_dir).joinpath(
            "gold/binance-public-data/v1/frequency=1min/dataset=trades",
            f"symbol={symbol}",
            f"period={period}",
            "scope=continuous-period",
        )
        manifest = root / "manifest.json"
        inputs[symbol] = sha256_file(manifest)
        bars = pd.read_parquet(
            root / "futures_um_bars.parquet",
            columns=["timestamp", "close", "buy_volume", "sell_volume"],
        )
        signal, threshold = quarter_hour_signal(
            bars,
            training_end=oos_start,
            period_start=pd.Timestamp(f"{period}-01T00:00:00Z"),
        )
        for horizon in HORIZONS_MINUTES:
            results.append(
                {
                    "family": "quarter_hour_order_flow_v0",
                    "symbol": symbol,
                    "horizon_minutes": horizon,
                    "training_abs_imbalance_quantile": TRAINING_QUANTILE,
                    "training_abs_imbalance_threshold": threshold,
                    **evaluate_event_signal(
                        bars[["timestamp", "close"]],
                        signal,
                        horizon_minutes=horizon,
                        cost_bps=13.0,
                        oos_start=oos_start,
                        oos_end=oos_end,
                    ),
                }
            )
    return {
        "schema_version": 1,
        "status": "EXPLORATORY_ONLY",
        "period": period,
        "dataset": "trades",
        "frequency": "1min",
        "measurement_window": "first_full_minute_of_each_utc_quarter_hour",
        "entry_delay_minutes": 1,
        "training_quantile": TRAINING_QUANTILE,
        "horizons_minutes": list(HORIZONS_MINUTES),
        "execution_cost_scenarios": EXECUTION_COST_SCENARIOS,
        "post_only_execution_sensitivity": POST_ONLY_EXECUTION_SENSITIVITY,
        "maker_fill_probability_mode": "SENSITIVITY_ONLY_NOT_EMPIRICALLY_CALIBRATED",
        "oos_start_utc": oos_start.isoformat(),
        "oos_end_utc": oos_end.isoformat(),
        "quality_report_sha256": sha256_file(quality_report_path),
        "preregistration_sha256": sha256_file(preregistration_path),
        "gold_manifest_sha256": inputs,
        "results": results,
        "promotion_allowed": False,
        "execution_allowed": False,
    }


def quarter_hour_signal(
    bars: pd.DataFrame,
    *,
    training_end: pd.Timestamp,
    period_start: pd.Timestamp,
) -> tuple[pd.DataFrame, float]:
    """Build a causal sign signal with its threshold frozen on prior bars."""
    required = {"timestamp", "buy_volume", "sell_volume"}
    if not required.issubset(bars.columns):
        raise ValueError(f"bars missing columns: {sorted(required - set(bars.columns))}")
    value = bars.copy()
    value["timestamp"] = pd.to_datetime(value["timestamp"], utc=True)
    value = value.sort_values("timestamp", kind="stable")
    opening = value["timestamp"] - pd.Timedelta(minutes=1)
    value = value[opening.dt.minute.mod(15).eq(0)].copy()
    total = value["buy_volume"].astype(float) + value["sell_volume"].astype(float)
    value["imbalance"] = (
        value["buy_volume"].astype(float) - value["sell_volume"].astype(float)
    ) / total.replace(0.0, np.nan)
    training = value[
        (value["timestamp"] >= period_start) & (value["timestamp"] < training_end)
    ]["imbalance"].dropna()
    if training.empty:
        raise ValueError("quarter-hour baseline has no training observations")
    threshold = float(training.abs().quantile(TRAINING_QUANTILE))
    if not np.isfinite(threshold) or threshold <= 0:
        raise ValueError("quarter-hour training threshold must be positive and finite")
    value["side"] = np.where(
        value["imbalance"].abs() >= threshold,
        np.sign(value["imbalance"]),
        0,
    ).astype(int)
    return value[["timestamp", "side"]], threshold
