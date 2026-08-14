"""The naive baseline every real model must beat out-of-sample, per
docs/PHASE_0_ARCHITECTURE_RESEARCH.md section 24: before anything else is
justified, it has to do better than the simplest possible predictor.

No ML dependency - this is pure arithmetic on the training labels.
"""

from __future__ import annotations

import numpy as np
import pandas as pd


class NaivePriorBaseline:
    """Predicts the training set's class prior for every row, regardless
    of features - ignores X entirely at predict time. A model that can't
    beat this isn't extracting any signal from the features.
    """

    def __init__(self) -> None:
        self._prior: float | None = None

    def fit(self, X: pd.DataFrame, y: np.ndarray) -> None:
        y = np.asarray(y)
        if len(y) == 0:
            raise ValueError("cannot fit on an empty label array")
        self._prior = float(np.mean(y))

    def predict_proba(self, X: pd.DataFrame) -> np.ndarray:
        if self._prior is None:
            raise RuntimeError("call fit() before predict_proba()")
        return np.full(len(X), self._prior)

    def predict(self, X: pd.DataFrame) -> np.ndarray:
        proba = self.predict_proba(X)
        return (proba >= 0.5).astype(int)
