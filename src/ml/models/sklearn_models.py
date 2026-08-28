"""Thin wrappers around scikit-learn estimators satisfying
src.ml.baseline.Model, for the section-24 "simple baseline" family:
Logistic Regression, Random Forest, Extra Trees. Binary classification only
(the first use case is setup scoring - P(win) - per docs/ML.md); regression
targets (expected return/R) are out of scope for this module.

`class_weight="balanced"` is used everywhere: trading labels are rarely
50/50 (e.g. a directional threshold label skews toward "flat"), and an
unweighted classifier would just learn to predict the majority class -
exactly the failure mode the naive baseline already exposes for free.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
from sklearn.ensemble import ExtraTreesClassifier, RandomForestClassifier
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler


class LogisticRegressionModel:
    def __init__(
        self, seed: int | None = None, max_iter: int = 1000, C: float = 1.0
    ) -> None:
        self._clf = make_pipeline(
            StandardScaler(),
            LogisticRegression(
                C=C, class_weight="balanced", max_iter=max_iter, random_state=seed
            ),
        )

    def fit(self, X: pd.DataFrame, y: np.ndarray) -> None:
        self._clf.fit(X, y)

    def predict(self, X: pd.DataFrame) -> np.ndarray:
        return self._clf.predict(X)

    def predict_proba(self, X: pd.DataFrame) -> np.ndarray:
        return self._clf.predict_proba(X)[:, 1]


class RandomForestModel:
    def __init__(
        self,
        seed: int | None = None,
        n_estimators: int = 200,
        max_depth: int | None = 5,
        min_samples_leaf: int = 1,
        n_jobs: int = -1,
    ) -> None:
        self._clf = RandomForestClassifier(
            n_estimators=n_estimators,
            max_depth=max_depth,
            min_samples_leaf=min_samples_leaf,
            class_weight="balanced",
            random_state=seed,
            n_jobs=n_jobs,
        )

    def fit(self, X: pd.DataFrame, y: np.ndarray) -> None:
        self._clf.fit(X, y)

    def predict(self, X: pd.DataFrame) -> np.ndarray:
        return self._clf.predict(X)

    def predict_proba(self, X: pd.DataFrame) -> np.ndarray:
        return self._clf.predict_proba(X)[:, 1]

    def feature_importances(self, feature_names: list[str]) -> pd.DataFrame:
        """Native impurity-based feature importance - reported alongside,
        never instead of, permutation importance (src.ml.explainability),
        per docs/ML.md's "no black-box model without diagnostics" rule.
        """
        return pd.DataFrame(
            {"feature": feature_names, "importance": self._clf.feature_importances_}
        ).sort_values("importance", ascending=False, ignore_index=True)


class ExtraTreesModel:
    def __init__(
        self,
        seed: int | None = None,
        n_estimators: int = 200,
        max_depth: int | None = 5,
        min_samples_leaf: int = 1,
        n_jobs: int = -1,
    ) -> None:
        self._clf = ExtraTreesClassifier(
            n_estimators=n_estimators,
            max_depth=max_depth,
            min_samples_leaf=min_samples_leaf,
            class_weight="balanced",
            random_state=seed,
            n_jobs=n_jobs,
        )

    def fit(self, X: pd.DataFrame, y: np.ndarray) -> None:
        self._clf.fit(X, y)

    def predict(self, X: pd.DataFrame) -> np.ndarray:
        return self._clf.predict(X)

    def predict_proba(self, X: pd.DataFrame) -> np.ndarray:
        return self._clf.predict_proba(X)[:, 1]

    def feature_importances(self, feature_names: list[str]) -> pd.DataFrame:
        return pd.DataFrame(
            {"feature": feature_names, "importance": self._clf.feature_importances_}
        ).sort_values("importance", ascending=False, ignore_index=True)
