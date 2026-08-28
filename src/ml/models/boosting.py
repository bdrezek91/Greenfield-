"""Resource-bounded gradient-boosting challengers for ML Tournament V1.

Both wrappers satisfy ``src.ml.baseline.Model`` and deliberately enforce the
training feature schema at prediction time.  A reordered/missing/extra column
is an error, never an implicit reinterpretation of a saved model.
"""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd
from lightgbm import LGBMClassifier
from xgboost import XGBClassifier


class _SchemaCheckedClassifier:
    _clf: Any

    def __init__(self) -> None:
        self._feature_columns: tuple[str, ...] | None = None

    def fit(self, X: pd.DataFrame, y: np.ndarray) -> None:
        _validate_training_data(X, y)
        self._feature_columns = tuple(X.columns)
        self._clf.fit(X, np.asarray(y, dtype=int))

    def predict(self, X: pd.DataFrame) -> np.ndarray:
        self._validate_schema(X)
        return np.asarray(self._clf.predict(X), dtype=int)

    def predict_proba(self, X: pd.DataFrame) -> np.ndarray:
        self._validate_schema(X)
        probabilities = np.asarray(self._clf.predict_proba(X), dtype=float)
        if probabilities.ndim != 2 or probabilities.shape[1] != 2:
            raise ValueError("binary classifier returned an invalid probability schema")
        positive = probabilities[:, 1]
        if not np.isfinite(positive).all() or ((positive < 0) | (positive > 1)).any():
            raise ValueError("classifier returned invalid probabilities")
        return positive

    def feature_importances(self, feature_names: list[str]) -> pd.DataFrame:
        if self._feature_columns is None:
            raise RuntimeError("model must be fitted before requesting feature importance")
        if tuple(feature_names) != self._feature_columns:
            raise ValueError("feature importance schema differs from fitted model schema")
        return pd.DataFrame(
            {"feature": feature_names, "importance": self._clf.feature_importances_}
        ).sort_values("importance", ascending=False, ignore_index=True)

    def _validate_schema(self, X: pd.DataFrame) -> None:
        if self._feature_columns is None:
            raise RuntimeError("model must be fitted before prediction")
        if tuple(X.columns) != self._feature_columns:
            raise ValueError(
                "prediction feature order/schema differs from training: "
                f"expected {self._feature_columns}, got {tuple(X.columns)}"
            )
        if X.isna().any().any() or not np.isfinite(X.to_numpy(dtype=float)).all():
            raise ValueError("prediction features must be finite and complete")


class XGBoostModel(_SchemaCheckedClassifier):
    def __init__(
        self,
        *,
        seed: int = 42,
        n_estimators: int = 200,
        max_depth: int = 3,
        learning_rate: float = 0.05,
        min_child_weight: float = 3.0,
        subsample: float = 0.8,
        colsample_bytree: float = 0.8,
        reg_alpha: float = 0.0,
        reg_lambda: float = 1.0,
    ) -> None:
        super().__init__()
        self._clf = XGBClassifier(
            n_estimators=n_estimators,
            max_depth=max_depth,
            learning_rate=learning_rate,
            min_child_weight=min_child_weight,
            subsample=subsample,
            colsample_bytree=colsample_bytree,
            reg_alpha=reg_alpha,
            reg_lambda=reg_lambda,
            objective="binary:logistic",
            eval_metric="logloss",
            random_state=seed,
            n_jobs=1,
            tree_method="hist",
        )


class LightGBMModel(_SchemaCheckedClassifier):
    def __init__(
        self,
        *,
        seed: int = 42,
        n_estimators: int = 200,
        max_depth: int = 4,
        learning_rate: float = 0.05,
        num_leaves: int = 15,
        min_child_samples: int = 40,
        subsample: float = 0.8,
        colsample_bytree: float = 0.8,
        reg_alpha: float = 0.0,
        reg_lambda: float = 1.0,
    ) -> None:
        super().__init__()
        self._clf = LGBMClassifier(
            n_estimators=n_estimators,
            max_depth=max_depth,
            learning_rate=learning_rate,
            num_leaves=num_leaves,
            min_child_samples=min_child_samples,
            subsample=subsample,
            subsample_freq=1,
            colsample_bytree=colsample_bytree,
            reg_alpha=reg_alpha,
            reg_lambda=reg_lambda,
            class_weight="balanced",
            random_state=seed,
            n_jobs=1,
            deterministic=True,
            force_col_wise=True,
            verbosity=-1,
        )


def _validate_training_data(X: pd.DataFrame, y: np.ndarray) -> None:
    labels = np.asarray(y)
    if X.empty or len(X) != len(labels):
        raise ValueError("training features/labels must be non-empty and aligned")
    if len(set(X.columns)) != len(X.columns):
        raise ValueError("training feature names must be unique")
    if X.isna().any().any() or not np.isfinite(X.to_numpy(dtype=float)).all():
        raise ValueError("training features must be finite and complete")
    unique = np.unique(labels)
    if not np.array_equal(unique, np.array([0, 1])):
        raise ValueError("binary tournament training requires both labels 0 and 1")
