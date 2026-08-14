from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from src.ml.evaluation import beats_baseline_every_fold, run_comparison, summarize_comparison
from src.ml.models.naive import NaivePriorBaseline
from src.ml.models.sklearn_models import LogisticRegressionModel


def _dataset(n: int = 300, seed: int = 0) -> tuple[pd.DataFrame, np.ndarray]:
    rng = np.random.default_rng(seed)
    x1 = rng.normal(size=n)
    y = (x1 > 0).astype(int)
    X = pd.DataFrame({"x1": x1, "noise": rng.normal(size=n)})
    return X, y


def _chronological_folds(n: int, n_splits: int) -> list[tuple[np.ndarray, np.ndarray]]:
    bounds = np.linspace(0, n, n_splits + 2, dtype=int)
    return [
        (np.arange(0, bounds[i]), np.arange(bounds[i], bounds[i + 1]))
        for i in range(1, n_splits + 1)
    ]


class TestRunComparison:
    def test_returns_one_row_per_model_per_fold(self) -> None:
        X, y = _dataset()
        folds = _chronological_folds(len(X), n_splits=3)
        factories = {
            "naive_prior": lambda: NaivePriorBaseline(),
            "logreg": lambda: LogisticRegressionModel(seed=0),
        }
        results = run_comparison(factories, X, y, folds)
        assert len(results) == len(factories) * len(folds)
        assert set(results["model_name"]) == set(factories)
        assert set(results["fold"]) == {0, 1, 2}

    def test_metrics_within_valid_ranges(self) -> None:
        X, y = _dataset()
        folds = _chronological_folds(len(X), n_splits=3)
        factories = {"logreg": lambda: LogisticRegressionModel(seed=0)}
        results = run_comparison(factories, X, y, folds)
        assert (results["accuracy"] >= 0).all() and (results["accuracy"] <= 1).all()
        assert (results["brier"] >= 0).all() and (results["brier"] <= 1).all()


class TestSummarizeComparison:
    def test_ranks_by_mean_brier_ascending(self) -> None:
        X, y = _dataset(n=400, seed=1)
        folds = _chronological_folds(len(X), n_splits=3)
        factories = {
            "naive_prior": lambda: NaivePriorBaseline(),
            "logreg": lambda: LogisticRegressionModel(seed=0),
        }
        results = run_comparison(factories, X, y, folds)
        summary = summarize_comparison(results)
        briers = summary[("brier", "mean")]
        assert list(briers.index) == list(briers.sort_values().index)


class TestBeatsBaselineEveryFold:
    def test_true_when_strictly_better_on_all_folds(self) -> None:
        results = pd.DataFrame(
            {
                "fold": [0, 0, 1, 1],
                "model_name": ["m", "naive_prior", "m", "naive_prior"],
                "brier": [0.1, 0.25, 0.1, 0.25],
            }
        )
        assert beats_baseline_every_fold(results, "m") is True

    def test_false_when_worse_on_one_fold(self) -> None:
        results = pd.DataFrame(
            {
                "fold": [0, 0, 1, 1],
                "model_name": ["m", "naive_prior", "m", "naive_prior"],
                "brier": [0.1, 0.25, 0.3, 0.25],
            }
        )
        assert beats_baseline_every_fold(results, "m") is False

    def test_missing_model_raises(self) -> None:
        results = pd.DataFrame(
            {"fold": [0], "model_name": ["naive_prior"], "brier": [0.25]}
        )
        with pytest.raises(ValueError):
            beats_baseline_every_fold(results, "nonexistent")
