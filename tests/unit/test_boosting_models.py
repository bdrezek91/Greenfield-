from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from src.ml.model_io import ModelMetadata, load_model, save_model
from src.ml.models.boosting import LightGBMModel, XGBoostModel


def _dataset(n: int = 180) -> tuple[pd.DataFrame, np.ndarray]:
    rng = np.random.default_rng(7)
    signal = rng.normal(size=n)
    X = pd.DataFrame({"signal": signal, "noise": rng.normal(size=n)})
    return X, (signal > 0).astype(int)


@pytest.mark.parametrize("model_cls", [XGBoostModel, LightGBMModel])
def test_boosting_fit_predict_is_deterministic_and_schema_checked(model_cls: type) -> None:
    X, y = _dataset()
    first = model_cls(seed=42, n_estimators=30)
    second = model_cls(seed=42, n_estimators=30)
    first.fit(X, y)
    second.fit(X, y)
    assert np.allclose(first.predict_proba(X), second.predict_proba(X))
    assert set(first.predict(X)).issubset({0, 1})
    with pytest.raises(ValueError, match="feature order/schema"):
        first.predict_proba(X[["noise", "signal"]])
    with pytest.raises(ValueError, match="finite and complete"):
        first.predict_proba(X.assign(signal=np.nan))


@pytest.mark.parametrize("model_cls", [XGBoostModel, LightGBMModel])
def test_boosting_requires_both_classes(model_cls: type) -> None:
    X, _ = _dataset()
    with pytest.raises(ValueError, match="both labels"):
        model_cls(n_estimators=10).fit(X, np.zeros(len(X), dtype=int))


@pytest.mark.parametrize("model_cls", [XGBoostModel, LightGBMModel])
def test_boosting_serialization_round_trip(model_cls: type, tmp_path: Path) -> None:
    X, y = _dataset()
    model = model_cls(seed=42, n_estimators=20)
    model.fit(X, y)
    expected = model.predict_proba(X.iloc[-10:])
    metadata = ModelMetadata(
        model_class=model_cls.__name__,
        feature_columns=tuple(X.columns),
        symbol="BTCUSDT",
        timeframe="1h",
        train_start="2024-01-01T00:00:00+00:00",
        train_end="2024-02-01T00:00:00+00:00",
        horizon_bars=24,
        label_type="setup_net_win",
        trained_at="2024-02-02T00:00:00+00:00",
        git_commit="test",
    )
    path = tmp_path / "model.joblib"
    save_model(model, metadata, path)
    loaded, loaded_metadata = load_model(path)
    assert loaded_metadata == metadata
    assert np.allclose(loaded.predict_proba(X.iloc[-10:]), expected)
