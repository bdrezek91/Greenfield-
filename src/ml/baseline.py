"""The `Model` contract every ML model in this project satisfies.

Per docs/PHASE_0_ARCHITECTURE_RESEARCH.md section 24: before anything
expensive, compare simple models (Logistic Regression, Random Forest,
Extra Trees) - and only LightGBM/XGBoost/CatBoost, and only deep learning
after that, if the simpler baseline is actually beaten out-of-sample. Phase
11 built the research FRAMEWORK (features, splits, calibration,
explainability) without training any model. Phase 12 (src/ml/models/)
populates it with the actual baseline comparison: NaivePriorBaseline (the
bar to beat) plus scikit-learn-backed Logistic Regression / Random Forest /
Extra Trees, evaluated through src/ml/evaluation.py.

`Model` predates the concrete implementations so downstream code
(src/ml/explainability.py:Predictor, src/ml/evaluation.py) had a stable
interface to target before any model existed.
"""

from __future__ import annotations

from typing import Protocol

import numpy as np
import pandas as pd


class Model(Protocol):
    def fit(self, X: pd.DataFrame, y: np.ndarray) -> None: ...
    def predict(self, X: pd.DataFrame) -> np.ndarray: ...
    def predict_proba(self, X: pd.DataFrame) -> np.ndarray: ...
