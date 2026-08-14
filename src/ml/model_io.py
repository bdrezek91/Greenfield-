"""Persist a trained model alongside the metadata needed to use it safely
later - same reproducibility discipline as src.analytics.experiment's
ExperimentRecord (section 20 of the project brief): a model artifact
without its feature schema, training window, and provenance is not
trustworthy to load into a strategy months later.

Trained artifacts are gitignored (`/reports/models/`, see .gitignore) -
they're generated from data, not source, same reasoning as
reports/experiments/*.jsonl.
"""

from __future__ import annotations

import json
import subprocess
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

import joblib


@dataclass(frozen=True)
class ModelMetadata:
    model_class: str
    feature_columns: tuple[str, ...]
    symbol: str
    timeframe: str
    train_start: str
    train_end: str
    horizon_bars: int
    label_type: str
    trained_at: str
    git_commit: str | None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @staticmethod
    def from_dict(data: dict[str, Any]) -> ModelMetadata:
        return ModelMetadata(**{**data, "feature_columns": tuple(data["feature_columns"])})


def current_git_commit() -> str | None:
    """Best-effort - None (not a hard failure) if git is unavailable or
    this isn't a git checkout, since that shouldn't block saving a model
    during local experimentation.
    """
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"], capture_output=True, text=True, timeout=5, check=True
        )
        return result.stdout.strip()
    except (subprocess.SubprocessError, OSError):
        return None


def save_model(model: object, metadata: ModelMetadata, path: Path) -> None:
    """Writes `path` (joblib-serialized model) and a `.json` sidecar with
    the same stem holding `metadata`.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    joblib.dump(model, path)
    path.with_suffix(".json").write_text(json.dumps(metadata.to_dict(), indent=2))


def load_model(path: Path) -> tuple[object, ModelMetadata]:
    """Raises FileNotFoundError if either the model file or its metadata
    sidecar is missing - loading a model without its feature schema is
    never allowed, since a caller has no way to know if the columns it's
    about to feed the model still match what it was trained on.
    """
    if not path.exists():
        raise FileNotFoundError(f"model file not found: {path}")
    metadata_path = path.with_suffix(".json")
    if not metadata_path.exists():
        raise FileNotFoundError(f"model metadata sidecar not found: {metadata_path}")

    model = joblib.load(path)
    metadata = ModelMetadata.from_dict(json.loads(metadata_path.read_text()))
    return model, metadata
