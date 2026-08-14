from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from src.ml.models.naive import NaivePriorBaseline
from src.ml.models.sklearn_models import ExtraTreesModel, LogisticRegressionModel, RandomForestModel


def _separable_dataset(n: int = 200, seed: int = 0) -> tuple[pd.DataFrame, np.ndarray]:
    rng = np.random.default_rng(seed)
    x1 = rng.normal(size=n)
    x2 = rng.normal(size=n)
    y = (x1 + 0.1 * x2 > 0).astype(int)
    X = pd.DataFrame({"x1": x1, "x2": x2, "noise": rng.normal(size=n)})
    return X, y


class TestNaivePriorBaseline:
    def test_predicts_constant_prior(self) -> None:
        X, y = _separable_dataset()
        model = NaivePriorBaseline()
        model.fit(X, y)
        proba = model.predict_proba(X)
        assert np.allclose(proba, y.mean())

    def test_predict_thresholds_at_half(self) -> None:
        X = pd.DataFrame({"x": [1.0, 2.0, 3.0]})
        model = NaivePriorBaseline()
        model.fit(X, np.array([1, 1, 0]))
        pred = model.predict(X)
        assert (pred == 1).all()

    def test_predict_proba_before_fit_raises(self) -> None:
        model = NaivePriorBaseline()
        with pytest.raises(RuntimeError):
            model.predict_proba(pd.DataFrame({"x": [1.0]}))

    def test_fit_on_empty_labels_raises(self) -> None:
        model = NaivePriorBaseline()
        with pytest.raises(ValueError):
            model.fit(pd.DataFrame({"x": []}), np.array([]))


@pytest.mark.parametrize("model_cls", [LogisticRegressionModel, RandomForestModel, ExtraTreesModel])
class TestSklearnModels:
    def test_fit_predict_shapes(self, model_cls: type) -> None:
        X, y = _separable_dataset()
        model = model_cls(seed=0)
        model.fit(X, y)
        pred = model.predict(X)
        proba = model.predict_proba(X)
        assert pred.shape == (len(X),)
        assert proba.shape == (len(X),)
        assert set(np.unique(pred)).issubset({0, 1})
        assert (proba >= 0).all() and (proba <= 1).all()

    def test_beats_naive_baseline_on_separable_data(self, model_cls: type) -> None:
        X, y = _separable_dataset(n=400, seed=1)
        split = 300
        X_train, y_train = X.iloc[:split], y[:split]
        X_test, y_test = X.iloc[split:], y[split:]

        naive = NaivePriorBaseline()
        naive.fit(X_train, y_train)
        naive_proba = naive.predict_proba(X_test)
        naive_brier = float(np.mean((naive_proba - y_test) ** 2))

        model = model_cls(seed=0)
        model.fit(X_train, y_train)
        proba = model.predict_proba(X_test)
        brier = float(np.mean((proba - y_test) ** 2))

        assert brier < naive_brier

    def test_deterministic_given_seed(self, model_cls: type) -> None:
        X, y = _separable_dataset()
        model_a = model_cls(seed=42)
        model_a.fit(X, y)
        model_b = model_cls(seed=42)
        model_b.fit(X, y)
        assert np.allclose(model_a.predict_proba(X), model_b.predict_proba(X))


class TestFeatureImportances:
    @pytest.mark.parametrize("model_cls", [RandomForestModel, ExtraTreesModel])
    def test_feature_importances_sum_to_one_and_favor_signal(self, model_cls: type) -> None:
        X, y = _separable_dataset(n=400, seed=2)
        model = model_cls(seed=0)
        model.fit(X, y)
        importances = model.feature_importances(list(X.columns))
        assert set(importances["feature"]) == set(X.columns)
        assert importances["importance"].sum() == pytest.approx(1.0, abs=1e-6)
        assert importances.iloc[0]["feature"] == "x1"
