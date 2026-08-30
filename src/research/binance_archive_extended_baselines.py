"""Frozen causal extended baselines for one audited Binance archive month."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from src.data.binance_public_archive import sha256_file
from src.research.binance_archive_baselines import (
    EXECUTION_COST_SCENARIOS,
    HORIZONS_MINUTES,
    ROUND_TRIP_COST_BPS,
    SYMBOLS,
    evaluate_event_signal,
    monthly_oos_bounds,
)

WINDOW = 240
THRESHOLD = 2.0


def run_binance_archive_extended_baselines(
    data_dir: Path,
    *,
    period: str,
    quality_report_path: Path,
    preregistration_path: Path,
) -> dict[str, Any]:
    """Evaluate four fixed families without parameter search or promotion."""
    quality = json.loads(Path(quality_report_path).read_text(encoding="utf-8"))
    if quality.get("period") != period or quality.get("dataset") != "trades":
        raise ValueError(f"extended baseline requires audited {period} trades")
    if quality.get("oos_ready") is not True:
        raise ValueError("extended baseline requires a positive OOS-ready report")
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
        bars = pd.read_parquet(root / "futures_um_bars.parquet")
        signals = {
            "trend_breakout_v1": _trend_breakout_signal(bars),
            "price_mean_reversion_v1": _price_mean_reversion_signal(bars),
            "order_flow_impulse_v1": _order_flow_impulse_signal(bars),
            "vwap_reversion_v1": _vwap_reversion_signal(bars),
        }
        for family, signal in signals.items():
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
        "schema_version": 2,
        "status": "EXPLORATORY_ONLY",
        "period": period,
        "dataset": "trades",
        "frequency": "1min",
        "oos_start_utc": oos_start.isoformat(),
        "oos_end_utc": oos_end.isoformat(),
        "round_trip_cost_bps": ROUND_TRIP_COST_BPS,
        "execution_cost_scenarios": EXECUTION_COST_SCENARIOS,
        "maker_fill_probability_modeled": False,
        "horizons_minutes": list(HORIZONS_MINUTES),
        "window": WINDOW,
        "threshold": THRESHOLD,
        "quality_report_sha256": sha256_file(quality_report_path),
        "preregistration_sha256": sha256_file(preregistration_path),
        "gold_manifest_sha256": inputs,
        "results": results,
        "promotion_allowed": False,
    }


def _trend_breakout_signal(bars: pd.DataFrame) -> pd.DataFrame:
    value = _ordered(bars)
    close = value["close"].astype(float)
    prior_high = close.shift(1).rolling(WINDOW, min_periods=WINDOW).max()
    prior_low = close.shift(1).rolling(WINDOW, min_periods=WINDOW).min()
    value["side"] = np.select([close > prior_high, close < prior_low], [1, -1], default=0)
    return value[["timestamp", "side"]]


def _price_mean_reversion_signal(bars: pd.DataFrame) -> pd.DataFrame:
    value = _ordered(bars)
    zscore = _causal_zscore(np.log(value["close"].astype(float)))
    value["side"] = np.select([zscore >= THRESHOLD, zscore <= -THRESHOLD], [-1, 1], 0)
    return value[["timestamp", "side"]]


def _order_flow_impulse_signal(bars: pd.DataFrame) -> pd.DataFrame:
    value = _ordered(bars)
    volume = value["volume"].astype(float).replace(0, np.nan)
    imbalance = value["trade_delta"].astype(float) / volume
    zscore = _causal_zscore(imbalance)
    value["side"] = np.select([zscore >= THRESHOLD, zscore <= -THRESHOLD], [1, -1], 0)
    return value[["timestamp", "side"]]


def _vwap_reversion_signal(bars: pd.DataFrame) -> pd.DataFrame:
    value = _ordered(bars)
    deviation = value["close"].astype(float) / value["trade_vwap"].astype(float) - 1.0
    zscore = _causal_zscore(deviation)
    value["side"] = np.select([zscore >= THRESHOLD, zscore <= -THRESHOLD], [-1, 1], 0)
    return value[["timestamp", "side"]]


def _causal_zscore(series: pd.Series) -> pd.Series:
    history = series.shift(1).rolling(WINDOW, min_periods=WINDOW)
    return (series - history.mean()) / history.std(ddof=0).replace(0, np.nan)


def _ordered(bars: pd.DataFrame) -> pd.DataFrame:
    required = {"timestamp", "close", "volume", "trade_delta", "trade_vwap"}
    if not required.issubset(bars.columns):
        raise ValueError(f"extended baseline bars missing: {sorted(required - set(bars.columns))}")
    return bars.sort_values("timestamp", kind="stable").reset_index(drop=True).copy()
