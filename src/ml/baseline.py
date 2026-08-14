"""Scaffold for Phase 12's baseline models - not implemented here.

Per docs/PHASE_0_ARCHITECTURE_RESEARCH.md section 24: before anything
expensive, compare simple models (Logistic Regression, Random Forest,
Extra Trees) - and only LightGBM/XGBoost/CatBoost, and only deep learning
after that, if the simpler baseline is actually beaten out-of-sample. Phase
11 (this phase) is the research FRAMEWORK - features, splits, calibration,
explainability - deliberately without training any model yet; Phase 12
populates this framework with the actual baseline comparison. No ML
library (scikit-learn/lightgbm) is installed until then, consistent with
this project's practice of not installing a dependency before code uses it
(see e.g. vectorbt's deferral through Phases 3-6).

`Model` is the contract Phase 12's implementations (and this module's
explainability/calibration consumers) are expected to satisfy - defined
now so downstream code (src/ml/explainability.py:Predictor,
scripts that will call into this) has a stable interface to target.
"""

from __future__ import annotations

from typing import Protocol

import numpy as np
import pandas as pd


class Model(Protocol):
    def fit(self, X: pd.DataFrame, y: np.ndarray) -> None: ...
    def predict(self, X: pd.DataFrame) -> np.ndarray: ...
    def predict_proba(self, X: pd.DataFrame) -> np.ndarray: ...
