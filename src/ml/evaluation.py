"""Baseline comparison harness: trains each candidate model on each purged
fold and reports out-of-sample metrics, always alongside the naive prior
baseline (src.ml.models.naive.NaivePriorBaseline) - per
docs/PHASE_0_ARCHITECTURE_RESEARCH.md section 24, a model only earns
consideration for anything more expensive once it beats this baseline
out-of-sample, on every fold, not just on average.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Protocol

import numpy as np
import pandas as pd
from sklearn.metrics import accuracy_score, roc_auc_score

from src.ml.calibration import brier_score


class ProbaModel(Protocol):
    def fit(self, X: pd.DataFrame, y: np.ndarray) -> None: ...
    def predict_proba(self, X: pd.DataFrame) -> np.ndarray: ...


@dataclass
class FoldResult:
    fold: int
    model_name: str
    n_train: int
    n_test: int
    accuracy: float
    roc_auc: float
    brier: float


def evaluate_fold(
    model_name: str,
    model_factory: Callable[[], ProbaModel],
    X: pd.DataFrame,
    y: np.ndarray,
    train_idx: np.ndarray,
    test_idx: np.ndarray,
    fold: int,
) -> FoldResult:
    """Fit a fresh model instance (from `model_factory`, so each fold gets
    an unfitted model - no state carried across folds) on `train_idx` and
    score it on `test_idx`. `roc_auc` is NaN if the test fold has only one
    class present (undefined in that case).
    """
    model = model_factory()
    y = np.asarray(y)
    X_train, y_train = X.iloc[train_idx], y[train_idx]
    X_test, y_test = X.iloc[test_idx], y[test_idx]

    model.fit(X_train, y_train)
    proba = model.predict_proba(X_test)
    pred = (proba >= 0.5).astype(int)

    roc_auc = float(roc_auc_score(y_test, proba)) if len(np.unique(y_test)) > 1 else float("nan")

    return FoldResult(
        fold=fold,
        model_name=model_name,
        n_train=len(train_idx),
        n_test=len(test_idx),
        accuracy=float(accuracy_score(y_test, pred)),
        roc_auc=roc_auc,
        brier=brier_score(y_test, proba),
    )


def run_comparison(
    model_factories: dict[str, Callable[[], ProbaModel]],
    X: pd.DataFrame,
    y: np.ndarray,
    folds: list[tuple[np.ndarray, np.ndarray]],
) -> pd.DataFrame:
    """Run every model in `model_factories` across every fold in `folds`
    (from src.ml.splits.purged_kfold_split) and return one row per
    (model, fold). Always include a "naive_prior" entry in
    `model_factories` so the comparison table has the baseline to beat
    built in, rather than computed separately and easy to forget.
    """
    results = []
    for fold_i, (train_idx, test_idx) in enumerate(folds):
        for model_name, factory in model_factories.items():
            results.append(
                evaluate_fold(model_name, factory, X, y, train_idx, test_idx, fold_i)
            )
    return pd.DataFrame([r.__dict__ for r in results])


def summarize_comparison(results: pd.DataFrame) -> pd.DataFrame:
    """Mean +/- std of each metric per model, across folds."""
    return (
        results.groupby("model_name")[["accuracy", "roc_auc", "brier"]]
        .agg(["mean", "std"])
        .sort_values(("brier", "mean"))
    )


def beats_baseline_every_fold(
    results: pd.DataFrame, model_name: str, baseline_name: str = "naive_prior"
) -> bool:
    """True only if `model_name` has a strictly lower Brier score than
    `baseline_name` on every single fold - matching the project's
    per-fold, not just on-average, robustness standard (see also
    docs/RESEARCH_METHODOLOGY.md on parameter robustness).
    """
    merged = results[results["model_name"].isin([model_name, baseline_name])]
    pivot = merged.pivot(index="fold", columns="model_name", values="brier")
    if model_name not in pivot.columns or baseline_name not in pivot.columns:
        raise ValueError(f"missing results for {model_name!r} or {baseline_name!r}")
    return bool((pivot[model_name] < pivot[baseline_name]).all())
