from __future__ import annotations

from pathlib import Path

import pytest

from src.ml.model_io import ModelMetadata, load_model, save_model


def _metadata(**overrides: object) -> ModelMetadata:
    base = dict(
        model_class="NaivePriorBaseline",
        feature_columns=("a", "b"),
        symbol="BTCUSDT",
        timeframe="1h",
        train_start="2024-01-01T00:00:00+00:00",
        train_end="2024-02-01T00:00:00+00:00",
        horizon_bars=24,
        label_type="direction_binary",
        trained_at="2024-02-01T01:00:00+00:00",
        git_commit="abc123",
    )
    base.update(overrides)
    return ModelMetadata(**base)  # type: ignore[arg-type]


class _DummyModel:
    def predict_proba(self, X: object) -> float:
        return 0.5


class TestSaveLoadRoundtrip:
    def test_roundtrip_preserves_model_and_metadata(self, tmp_path: Path) -> None:
        model = _DummyModel()
        metadata = _metadata()
        path = tmp_path / "model.joblib"

        save_model(model, metadata, path)
        loaded_model, loaded_metadata = load_model(path)

        assert loaded_model.predict_proba(None) == 0.5
        assert loaded_metadata == metadata

    def test_creates_json_sidecar(self, tmp_path: Path) -> None:
        path = tmp_path / "nested" / "model.joblib"
        save_model(_DummyModel(), _metadata(), path)
        assert path.exists()
        assert path.with_suffix(".json").exists()

    def test_feature_columns_survive_as_tuple(self, tmp_path: Path) -> None:
        path = tmp_path / "model.joblib"
        save_model(_DummyModel(), _metadata(feature_columns=("x", "y", "z")), path)
        _, metadata = load_model(path)
        assert metadata.feature_columns == ("x", "y", "z")
        assert isinstance(metadata.feature_columns, tuple)


class TestLoadMissingFiles:
    def test_missing_model_file_raises(self, tmp_path: Path) -> None:
        with pytest.raises(FileNotFoundError):
            load_model(tmp_path / "does_not_exist.joblib")

    def test_missing_metadata_sidecar_raises(self, tmp_path: Path) -> None:
        path = tmp_path / "model.joblib"
        import joblib

        joblib.dump(_DummyModel(), path)  # no metadata sidecar written
        with pytest.raises(FileNotFoundError):
            load_model(path)
