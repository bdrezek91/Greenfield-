"""Phase 13: MLFiltered must only trade when BOTH the base momentum signal
fires AND the model's P(win) clears the threshold - and must never trade
in-sample (bars at/before the model's recorded train_end), even when both
of those are true.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from src.features.pipeline import FEATURE_COLUMNS
from src.ml.model_io import ModelMetadata, save_model
from src.strategies.ml_filtered import MLFiltered, MLFilteredConfig
from tests.integration.helpers import run_strategy


class _ConstantProbaModel:
    """A minimal stand-in for a real Model - predicts a fixed probability
    regardless of features, so tests can isolate the filter's threshold
    logic from any real model's behavior.
    """

    def __init__(self, proba: float) -> None:
        self._proba = proba

    def predict_proba(self, X: object) -> np.ndarray:
        return np.array([self._proba])


def _save_model(tmp_path: Path, proba: float, train_end: str) -> str:
    path = tmp_path / "model.joblib"
    metadata = ModelMetadata(
        model_class="_ConstantProbaModel",
        feature_columns=FEATURE_COLUMNS,
        symbol="BTCUSDT",
        timeframe="1h",
        train_start="2020-01-01T00:00:00+00:00",
        train_end=train_end,
        horizon_bars=24,
        label_type="direction_binary",
        trained_at="2020-01-01T00:00:00+00:00",
        git_commit=None,
    )
    save_model(_ConstantProbaModel(proba), metadata, path)
    return str(path)


# Trending series with clear momentum, long enough for the default
# feature_warmup_bars=150 plus the momentum lookback.
_TRENDING_CLOSE = 100 + np.arange(250, dtype=float) * 0.5


class TestMLFilteredThreshold:
    def test_trades_when_model_approves(self, tmp_path: Path) -> None:
        model_path = _save_model(tmp_path, proba=0.9, train_end="2020-01-01T00:00:00+00:00")
        positions, _ = run_strategy(
            tmp_path,
            _TRENDING_CLOSE,
            MLFiltered,
            MLFilteredConfig,
            model_path=model_path,
            probability_threshold=0.55,
            feature_warmup_bars=150,
        )
        assert len(positions) > 0
        assert (positions["entry"] == "BUY").all()

    def test_stays_flat_when_model_rejects(self, tmp_path: Path) -> None:
        model_path = _save_model(tmp_path, proba=0.1, train_end="2020-01-01T00:00:00+00:00")
        positions, _ = run_strategy(
            tmp_path,
            _TRENDING_CLOSE,
            MLFiltered,
            MLFilteredConfig,
            model_path=model_path,
            probability_threshold=0.55,
            feature_warmup_bars=150,
        )
        assert len(positions) == 0

    def test_stays_flat_without_base_momentum_signal(self, tmp_path: Path) -> None:
        model_path = _save_model(tmp_path, proba=0.99, train_end="2020-01-01T00:00:00+00:00")
        flat_close = np.full(250, 100.0)
        positions, _ = run_strategy(
            tmp_path,
            flat_close,
            MLFiltered,
            MLFilteredConfig,
            model_path=model_path,
            probability_threshold=0.55,
            feature_warmup_bars=150,
        )
        assert len(positions) == 0


class TestMLFilteredInSampleGuard:
    def test_never_trades_at_or_before_train_end(self, tmp_path: Path) -> None:
        # train_end far in the future relative to the whole synthetic series -
        # every bar in this backtest is "in-sample" and must be refused.
        model_path = _save_model(tmp_path, proba=0.99, train_end="2030-01-01T00:00:00+00:00")
        positions, _ = run_strategy(
            tmp_path,
            _TRENDING_CLOSE,
            MLFiltered,
            MLFilteredConfig,
            model_path=model_path,
            probability_threshold=0.55,
            feature_warmup_bars=150,
        )
        assert len(positions) == 0


class TestMLFilteredSchemaGuard:
    def test_raises_on_feature_column_mismatch(self, tmp_path: Path) -> None:
        path = tmp_path / "bad_model.joblib"
        bad_metadata = ModelMetadata(
            model_class="_ConstantProbaModel",
            feature_columns=("only_one_feature",),
            symbol="BTCUSDT",
            timeframe="1h",
            train_start="2020-01-01T00:00:00+00:00",
            train_end="2020-01-01T00:00:00+00:00",
            horizon_bars=24,
            label_type="direction_binary",
            trained_at="2020-01-01T00:00:00+00:00",
            git_commit=None,
        )
        save_model(_ConstantProbaModel(0.9), bad_metadata, path)

        with pytest.raises(ValueError, match="feature schema"):
            run_strategy(
                tmp_path,
                _TRENDING_CLOSE,
                MLFiltered,
                MLFilteredConfig,
                model_path=str(path),
                feature_warmup_bars=150,
            )
