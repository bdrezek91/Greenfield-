from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from src.features.pipeline import FEATURE_COLUMNS
from src.ml.tournament import (
    ADVERSE_COST,
    BASE_COST,
    HORIZON_BARS,
    PayoffEstimate,
    PlattCalibrator,
    build_setup_dataset,
    build_triple_barrier_setup_dataset,
    cost_aware_trade_mask,
    expanding_walk_forward_splits,
    split_fit_and_calibration,
)


def _klines(n: int = 2200) -> pd.DataFrame:
    rng = np.random.default_rng(11)
    returns = rng.normal(0, 0.003, n)
    close = 100 * np.exp(np.cumsum(returns))
    # Periodic causal jumps ensure enough Breakout candidates/classes.
    close[::80] *= 1.03
    timestamp = pd.date_range("2022-01-01", periods=n, freq="h", tz="UTC")
    return pd.DataFrame(
        {
            "timestamp": timestamp,
            "open": close * 0.999,
            "high": close * 1.002,
            "low": close * 0.998,
            "close": close,
            "volume": rng.uniform(100, 200, n),
        }
    )


def _pooled_dataset() -> pd.DataFrame:
    frames = [
        build_setup_dataset(_klines(), symbol=symbol)
        for symbol in ("BTCUSDT", "ETHUSDT", "SOLUSDT")
    ]
    return (
        pd.concat(frames, ignore_index=True)
        .sort_values(["timestamp", "symbol"])
        .reset_index(drop=True)
    )


def test_setup_dataset_is_non_overlapping_causal_and_complete() -> None:
    dataset = build_setup_dataset(_klines(), symbol="BTCUSDT")
    assert not dataset.empty
    assert set(FEATURE_COLUMNS).issubset(dataset.columns)
    assert dataset[list(FEATURE_COLUMNS)].notna().all().all()
    assert set(dataset["label"].unique()).issubset({0, 1})
    positions = dataset["timestamp"].map(
        {timestamp: i for i, timestamp in enumerate(_klines()["timestamp"])}
    )
    assert (positions.diff().dropna() > HORIZON_BARS).all()
    assert (dataset["label_end_time"] > dataset["timestamp"]).all()


def test_triple_barrier_dataset_keeps_identical_candidates_and_causal_features() -> None:
    fixed = build_setup_dataset(_klines(), symbol="BTCUSDT")
    triple = build_triple_barrier_setup_dataset(_klines(), symbol="BTCUSDT")
    assert triple["timestamp"].tolist() == fixed["timestamp"].tolist()
    assert triple["side"].tolist() == fixed["side"].tolist()
    assert triple[list(FEATURE_COLUMNS)].equals(fixed[list(FEATURE_COLUMNS)])
    assert set(triple["barrier"]).issubset({"PROFIT_TAKE", "STOP_LOSS", "VERTICAL"})
    assert (triple["label_end_time"] <= fixed["label_end_time"]).all()
    assert (triple["label_end_time"] > triple["timestamp"]).all()


def test_walk_forward_is_past_only_purged_and_holdout_is_last() -> None:
    dataset = _pooled_dataset()
    folds, holdout = expanding_walk_forward_splits(dataset, n_splits=3)
    assert len(folds) == 3
    for split in [*folds, holdout]:
        train = dataset.iloc[split.train_index]
        test = dataset.iloc[split.test_index]
        assert train["label_end_time"].max() < test["timestamp"].min()
        assert set(split.train_index).isdisjoint(split.test_index)
    assert (
        dataset.iloc[holdout.test_index]["timestamp"].min()
        > dataset.iloc[folds[-1].test_index]["timestamp"].max()
    )


def test_calibration_tail_is_disjoint_and_after_fit_window() -> None:
    dataset = _pooled_dataset()
    folds, _ = expanding_walk_forward_splits(dataset, n_splits=3)
    fit, calibration = split_fit_and_calibration(dataset, folds[-1].train_index)
    assert set(fit).isdisjoint(calibration)
    assert dataset.iloc[fit]["label_end_time"].max() < dataset.iloc[calibration]["timestamp"].min()


def test_platt_calibration_validates_classes_and_probabilities() -> None:
    calibrator = PlattCalibrator(seed=42)
    raw = np.linspace(0.05, 0.95, 40)
    labels = np.array([0] * 20 + [1] * 20)
    calibrator.fit(raw, labels)
    calibrated = calibrator.predict(np.array([0.2, 0.8]))
    assert 0 <= calibrated[0] < calibrated[1] <= 1
    with pytest.raises(ValueError, match="both labels"):
        PlattCalibrator().fit(raw, np.ones(40))


def test_cost_aware_gate_prefers_wait_and_is_monotone_in_costs() -> None:
    payoff = PayoffEstimate(0.01, -0.008)
    probabilities = np.array([0.45, 0.58, 0.90])
    base_mask, base_edge = cost_aware_trade_mask(probabilities, payoff, BASE_COST)
    adverse_mask, adverse_edge = cost_aware_trade_mask(probabilities, payoff, ADVERSE_COST)
    assert base_mask.tolist() == [False, False, True]
    assert (adverse_edge < base_edge).all()
    assert (adverse_mask <= base_mask).all()
