from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from src.data.storage import write_klines
from src.ml.models.boosting import LightGBMModel, XGBoostModel
from src.ml.models.sklearn_models import (
    ExtraTreesModel,
    LogisticRegressionModel,
    RandomForestModel,
)
from src.ml.tournament import SYMBOLS
from src.ml.tournament_runner import TrialSpec, run_tournament, write_tournament_report


def _klines(symbol: str, n: int = 5000) -> pd.DataFrame:
    rng = np.random.default_rng(100 + SYMBOLS.index(symbol))
    returns = rng.normal(0, 0.004, n)
    close = 100 * np.exp(np.cumsum(returns))
    timestamp = pd.date_range("2021-01-01", periods=n, freq="h", tz="UTC")
    return pd.DataFrame(
        {
            "timestamp": timestamp,
            "symbol": symbol,
            "timeframe": "1h",
            "open": close * 0.999,
            "high": close * 1.003,
            "low": close * 0.997,
            "close": close,
            "volume": rng.uniform(100, 500, n),
            "turnover": close * rng.uniform(100, 500, n),
        }
    )


def _small_specs(seed: int = 42) -> tuple[TrialSpec, ...]:
    return (
        TrialSpec("logistic", "logistic_regression", {}, lambda: LogisticRegressionModel(seed)),
        TrialSpec(
            "rf", "random_forest", {}, lambda: RandomForestModel(seed, 20, 4, 5, 1)
        ),
        TrialSpec("extra", "extra_trees", {}, lambda: ExtraTreesModel(seed, 20, 4, 5, 1)),
        TrialSpec("xgb", "xgboost", {}, lambda: XGBoostModel(seed=seed, n_estimators=20)),
        TrialSpec("lgbm", "lightgbm", {}, lambda: LightGBMModel(seed=seed, n_estimators=20)),
    )


def test_end_to_end_tournament_uses_all_families_and_writes_strict_json(
    tmp_path: Path, monkeypatch
) -> None:
    for symbol in SYMBOLS:
        write_klines(_klines(symbol), tmp_path)
    monkeypatch.setattr("src.ml.tournament_runner.frozen_trial_specs", _small_specs)

    ledger_path = tmp_path / "trial_ledger.jsonl"
    report = run_tournament(tmp_path, n_splits=2, trial_ledger_path=ledger_path)
    assert report["live_trading"] is False
    assert set(report["selected_trials"]) == {
        "logistic_regression",
        "random_forest",
        "extra_trees",
        "xgboost",
        "lightgbm",
    }
    assert set(report["dataset"]["rows_per_symbol"]) == set(SYMBOLS)
    assert report["verdict"] in {"PROMISING", "INCONCLUSIVE", "REJECT"}
    assert report["winner"] is None or report["winner"] in report["ranking"]
    assert len(ledger_path.read_text().splitlines()) == 5
    for result in report["holdout_results"]:
        assert set(result["scenarios"]) == {"base", "adverse", "severe"}
        assert set(result["per_symbol"]) == set(SYMBOLS)

    path = tmp_path / "report.json"
    write_tournament_report(report, path)
    assert json.loads(path.read_text())["ranking"] == report["ranking"]

    with pytest.raises(ValueError, match="already used"):
        run_tournament(tmp_path, n_splits=2, trial_ledger_path=ledger_path)
