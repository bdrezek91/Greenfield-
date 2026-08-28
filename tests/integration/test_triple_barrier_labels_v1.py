from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from src.data.storage import write_klines
from src.ml.models.sklearn_models import LogisticRegressionModel
from src.ml.tournament import SYMBOLS
from src.ml.tournament_runner import TrialSpec
from src.ml.triple_barrier_runner import (
    load_matched_label_datasets,
    run_triple_barrier_screen,
    write_triple_barrier_report,
)


def _klines(symbol: str, n: int = 5000) -> pd.DataFrame:
    rng = np.random.default_rng(400 + SYMBOLS.index(symbol))
    returns = rng.normal(0, 0.005, n)
    close = 100 * np.exp(np.cumsum(returns))
    timestamp = pd.date_range("2021-01-01", periods=n, freq="h", tz="UTC")
    return pd.DataFrame(
        {
            "timestamp": timestamp,
            "symbol": symbol,
            "timeframe": "1h",
            "open": close * 0.999,
            "high": close * 1.004,
            "low": close * 0.996,
            "close": close,
            "volume": rng.uniform(100, 500, n),
            "turnover": close * rng.uniform(100, 500, n),
        }
    )


def _one_spec() -> tuple[TrialSpec, ...]:
    return (
        TrialSpec(
            "logistic-c0.1",
            "logistic_regression",
            {"C": 0.1},
            lambda: LogisticRegressionModel(seed=42, C=0.1),
        ),
    )


def test_matched_triple_barrier_screen_is_development_only_and_idempotent(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    for symbol in SYMBOLS:
        write_klines(_klines(symbol), tmp_path)
    fixed, triple, metadata = load_matched_label_datasets(tmp_path)
    assert metadata["matched_rows"] == len(fixed) == len(triple)
    assert fixed[["timestamp", "symbol", "side"]].equals(
        triple[["timestamp", "symbol", "side"]]
    )
    monkeypatch.setattr("src.ml.triple_barrier_runner.frozen_label_specs", _one_spec)

    ledger = tmp_path / "trial_ledger.jsonl"
    report = run_triple_barrier_screen(tmp_path, trial_ledger_path=ledger, n_splits=2)
    assert report["live_trading"] is False
    assert report["holdout_used"] is False
    assert report["split"]["consumed_v1_holdout_excluded"] is True
    assert len(report["trials"]) == 2
    assert {trial["label"] for trial in report["trials"]} == {
        "fixed_horizon",
        "triple_barrier",
    }
    assert len(ledger.read_text().splitlines()) == 2

    path = tmp_path / "report.json"
    write_triple_barrier_report(report, path)
    assert json.loads(path.read_text())["verdict"] == report["verdict"]
    with pytest.raises(ValueError, match="already evaluated"):
        run_triple_barrier_screen(tmp_path, trial_ledger_path=ledger, n_splits=2)
