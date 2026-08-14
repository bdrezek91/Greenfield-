"""permutation_importance must correctly attribute error increase to
features the model actually uses, and (near-)zero to ones it ignores.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from src.ml.explainability import permutation_importance


class _UsesOnlyA:
    def predict(self, X: pd.DataFrame) -> np.ndarray:
        return X["a"].to_numpy() * 2.0


class _ConstantModel:
    def predict(self, X: pd.DataFrame) -> np.ndarray:
        return np.zeros(len(X))


def _mse(y_true: np.ndarray, y_pred: np.ndarray) -> float:
    return float(np.mean((y_true - y_pred) ** 2))


def test_ignored_feature_has_zero_importance() -> None:
    rng = np.random.default_rng(0)
    n = 200
    X = pd.DataFrame({"a": rng.normal(size=n), "b": rng.normal(size=n)})
    y = X["a"].to_numpy() * 2.0

    result = permutation_importance(_UsesOnlyA(), X, y, _mse, n_repeats=15, seed=1)
    df = result.as_dataframe()

    b_row = df[df["feature"] == "b"].iloc[0]
    assert b_row["importance_mean"] == pytest.approx(0.0, abs=1e-9)
    assert b_row["importance_std"] == pytest.approx(0.0, abs=1e-9)


def test_used_feature_has_positive_importance() -> None:
    rng = np.random.default_rng(0)
    n = 200
    X = pd.DataFrame({"a": rng.normal(size=n), "b": rng.normal(size=n)})
    y = X["a"].to_numpy() * 2.0

    result = permutation_importance(_UsesOnlyA(), X, y, _mse, n_repeats=15, seed=1)
    df = result.as_dataframe()

    a_row = df[df["feature"] == "a"].iloc[0]
    assert a_row["importance_mean"] > 0


def test_results_sorted_descending_by_importance() -> None:
    rng = np.random.default_rng(0)
    n = 200
    X = pd.DataFrame({"a": rng.normal(size=n), "b": rng.normal(size=n)})
    y = X["a"].to_numpy() * 2.0

    df = permutation_importance(_UsesOnlyA(), X, y, _mse, n_repeats=10, seed=1).as_dataframe()
    assert df.iloc[0]["feature"] == "a"


def test_constant_model_has_zero_importance_for_everything() -> None:
    rng = np.random.default_rng(0)
    n = 100
    X = pd.DataFrame({"a": rng.normal(size=n), "b": rng.normal(size=n)})
    y = np.zeros(n)

    df = permutation_importance(_ConstantModel(), X, y, _mse, n_repeats=10, seed=1).as_dataframe()
    assert np.allclose(df["importance_mean"].to_numpy(), 0.0, atol=1e-9)


def test_higher_is_better_flips_sign_convention() -> None:
    rng = np.random.default_rng(0)
    n = 200
    X = pd.DataFrame({"a": rng.normal(size=n), "b": rng.normal(size=n)})
    y = X["a"].to_numpy() * 2.0

    def neg_mse(y_true: np.ndarray, y_pred: np.ndarray) -> float:
        return -_mse(y_true, y_pred)  # a "higher is better" score

    df = permutation_importance(
        _UsesOnlyA(), X, y, neg_mse, n_repeats=15, seed=1, higher_is_better=True
    ).as_dataframe()
    a_row = df[df["feature"] == "a"].iloc[0]
    assert a_row["importance_mean"] > 0  # still positive despite the flipped metric direction


def test_output_covers_every_column() -> None:
    X = pd.DataFrame({"x": [1.0, 2.0, 3.0], "y": [4.0, 5.0, 6.0]})
    y = np.array([1.0, 2.0, 3.0])
    result = permutation_importance(_ConstantModel(), X, y, _mse, n_repeats=3, seed=0)
    assert set(result.feature) == {"x", "y"}
