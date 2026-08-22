"""CLI: fit one Phase 12 model on a full date range and export it as a
frozen artifact (src/ml/model_io.py) for src/strategies/ml_filtered.py to
load - the "frozen, versioned scikit-learn artifact" that stands in for the
research pipeline's live training loop when a strategy runs.

This does NOT evaluate the model - src/ml/evaluation.py already does that
via purged cross-validation (scripts/train_baseline_models.py). This
script only fits the FINAL model on everything in [start, end) so it can be
exported; validating it out-of-sample is the caller's job, via
docs/RESEARCH_METHODOLOGY.md's rule - and src/strategies/ml_filtered.py's
own train_end guard - never trade on [start, end).

Usage:
    python scripts/export_ml_model.py --symbol BTCUSDT --timeframe 1h \
        --start 2024-01-01 --end 2024-04-01 --horizon-bars 24 \
        --model logistic_regression --out reports/models/btc_1h_logreg
"""

from __future__ import annotations

import os
from collections.abc import Callable
from pathlib import Path

import pandas as pd
import structlog
import typer

from src.data.config import load_symbol_universe
from src.data.storage import read_klines
from src.features.pipeline import FEATURE_COLUMNS, build_feature_matrix
from src.ml.evaluation import ProbaModel
from src.ml.labels import forward_return_label
from src.ml.model_io import ModelMetadata, current_git_commit, save_model
from src.ml.models.naive import NaivePriorBaseline
from src.ml.models.sklearn_models import (
    ExtraTreesModel,
    LogisticRegressionModel,
    RandomForestModel,
)

log = structlog.get_logger()
app = typer.Typer(add_completion=False)

_MODEL_FACTORIES: dict[str, Callable[[int], ProbaModel]] = {
    "naive_prior": lambda seed: NaivePriorBaseline(),
    "logistic_regression": lambda seed: LogisticRegressionModel(seed=seed),
    "random_forest": lambda seed: RandomForestModel(seed=seed),
    "extra_trees": lambda seed: ExtraTreesModel(seed=seed),
}


@app.command()
def export(
    symbol: str = typer.Option(..., help="Single symbol, e.g. BTCUSDT."),
    timeframe: str = typer.Option("1h", help="Timeframe, e.g. 1h."),
    start: str = typer.Option(..., help="Training start date, e.g. 2024-01-01"),
    end: str = typer.Option(..., help="Training end date, e.g. 2024-04-01"),
    data_dir: str | None = typer.Option(None, help="Defaults to $DATA_DIR or ./data"),
    horizon_bars: int = typer.Option(24, help="Forward-return label horizon, in bars."),
    model: str = typer.Option(
        "logistic_regression", help=f"One of {list(_MODEL_FACTORIES)}."
    ),
    out: str = typer.Option(..., help="Output path stem, e.g. reports/models/btc_1h_logreg"),
    seed: int = typer.Option(42, help="Random seed."),
) -> None:
    if model not in _MODEL_FACTORIES:
        raise typer.BadParameter(
            f"unknown model {model!r}, expected one of {list(_MODEL_FACTORIES)}",
            param_hint="--model",
        )

    universe = load_symbol_universe()
    try:
        universe.validate_symbol(symbol)
        universe.validate_timeframe(timeframe)
    except ValueError as exc:
        raise typer.BadParameter(str(exc)) from exc

    resolved_data_dir = Path(data_dir or os.environ.get("DATA_DIR", "./data"))
    start_ts = pd.Timestamp(start, tz="UTC")
    end_ts = pd.Timestamp(end, tz="UTC")

    klines = read_klines(resolved_data_dir, symbol, timeframe, start=start_ts, end=end_ts)
    if klines.empty:
        log.warning("no data found", symbol=symbol, timeframe=timeframe)
        return

    features = build_feature_matrix(klines)
    label = forward_return_label(klines, horizon_bars=horizon_bars)

    dataset = features.copy()
    dataset["label"] = (label["label"] > 0).astype("float64")
    dataset.loc[label["label"].isna(), "label"] = float("nan")
    dataset = dataset.dropna(subset=[*FEATURE_COLUMNS, "label"]).reset_index(drop=True)

    if dataset.empty:
        log.warning("no rows left after dropping NaN feature/label rows - date range too short")
        return

    X = dataset[list(FEATURE_COLUMNS)]
    y = dataset["label"].to_numpy()

    fitted = _MODEL_FACTORIES[model](seed)
    fitted.fit(X, y)

    metadata = ModelMetadata(
        model_class=type(fitted).__name__,
        feature_columns=FEATURE_COLUMNS,
        symbol=symbol,
        timeframe=timeframe,
        train_start=str(dataset["timestamp"].iloc[0]),
        train_end=str(dataset["timestamp"].iloc[-1]),
        horizon_bars=horizon_bars,
        label_type="direction_binary",
        trained_at=str(pd.Timestamp.now(tz="UTC")),
        git_commit=current_git_commit(),
    )
    out_path = Path(out).with_suffix(".joblib")
    save_model(fitted, metadata, out_path)
    log.info(
        "model exported",
        path=str(out_path),
        n_rows=len(dataset),
        train_end=metadata.train_end,
        positive_rate=float(y.mean()),
    )


if __name__ == "__main__":
    app()
