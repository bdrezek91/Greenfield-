"""Model-agnostic explainability, per docs/PHASE_0_ARCHITECTURE_RESEARCH.md
section 27: report feature importance, permutation importance, and SHAP
where applicable. No black-box model without diagnostics.

Only permutation importance is implemented here - it needs nothing beyond
a fitted model's `.predict()` (any `Predictor` protocol implementation:
scikit-learn-style estimators, or anything else with the same shape), so
it works without an ML dependency installed. Native feature importance
(e.g. `.feature_importances_` on tree models) and SHAP require an actual
model implementation and library, which land with the first real models in
Phase 12 - see src/ml/baseline.py.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Protocol

import numpy as np
import pandas as pd


class Predictor(Protocol):
    def predict(self, X: pd.DataFrame) -> np.ndarray: ...


@dataclass
class PermutationImportanceResult:
    feature: list[str]
    importance_mean: np.ndarray
    """Mean increase in the error metric when the feature is shuffled,
    across `n_repeats` - higher means the model relies on it more."""
    importance_std: np.ndarray

    def as_dataframe(self) -> pd.DataFrame:
        return pd.DataFrame(
            {
                "feature": self.feature,
                "importance_mean": self.importance_mean,
                "importance_std": self.importance_std,
            }
        ).sort_values("importance_mean", ascending=False, ignore_index=True)


def permutation_importance(
    model: Predictor,
    X: pd.DataFrame,
    y: np.ndarray,
    metric_fn: Callable[[np.ndarray, np.ndarray], float],
    n_repeats: int = 10,
    seed: int | None = None,
    higher_is_better: bool = False,
) -> PermutationImportanceResult:
    """For each column, shuffle it `n_repeats` times and measure how much
    the model's error (per `metric_fn(y_true, y_pred)`) increases -
    features the model doesn't actually use will show ~zero importance
    regardless of any native "importance" the model itself might report.

    `higher_is_better=False` (default) assumes `metric_fn` is a loss (lower
    is better, e.g. Brier score) - importance is `shuffled_error -
    baseline_error`. Set `higher_is_better=True` for a score metric
    (higher is better) - importance is then `baseline_score - shuffled_score`,
    keeping "more important" always positive either way.
    """
    rng = np.random.default_rng(seed)
    baseline_pred = model.predict(X)
    baseline = metric_fn(y, baseline_pred)

    means = []
    stds = []
    for column in X.columns:
        deltas = []
        for _ in range(n_repeats):
            shuffled = X.copy()
            shuffled[column] = rng.permutation(shuffled[column].to_numpy())
            shuffled_pred = model.predict(shuffled)
            shuffled_metric = metric_fn(y, shuffled_pred)
            delta = (
                (baseline - shuffled_metric) if higher_is_better else (shuffled_metric - baseline)
            )
            deltas.append(delta)
        means.append(float(np.mean(deltas)))
        stds.append(float(np.std(deltas, ddof=1)) if n_repeats > 1 else 0.0)

    return PermutationImportanceResult(
        feature=list(X.columns), importance_mean=np.array(means), importance_std=np.array(stds)
    )
