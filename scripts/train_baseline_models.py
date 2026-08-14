"""CLI: run the Phase 12 baseline model comparison end to end on real data.

load klines -> build features (Phase 11) -> binary direction label ->
purged/embargoed folds (Phase 11) -> train naive/logreg/random-forest/
extra-trees per fold -> report accuracy/ROC-AUC/Brier per fold and
averaged, plus which models beat the naive baseline on EVERY fold (not
just on average) -> permutation importance and calibration curve for the
best model by mean Brier score.

Per docs/PHASE_0_ARCHITECTURE_RESEARCH.md section 24: nothing more
expensive than these three models is justified unless one of them clears
the naive baseline out-of-sample first.

Usage:
    python scripts/train_baseline_models.py --symbol BTCUSD --timeframe 1h \
        --start 2024-01-01 --end 2024-06-01 --horizon-bars 24 --n-splits 5
"""

from __future__ import annotations

import os
from pathlib import Path

import pandas as pd
import structlog
import typer

from src.data.config import load_symbol_universe
from src.data.storage import read_klines
from src.features.pipeline import FEATURE_COLUMNS, build_feature_matrix
from src.ml.calibration import brier_score, calibration_curve
from src.ml.evaluation import beats_baseline_every_fold, run_comparison, summarize_comparison
from src.ml.explainability import permutation_importance
from src.ml.labels import forward_return_label
from src.ml.models.naive import NaivePriorBaseline
from src.ml.models.sklearn_models import (
    ExtraTreesModel,
    LogisticRegressionModel,
    RandomForestModel,
)
from src.ml.splits import purged_kfold_split

log = structlog.get_logger()
app = typer.Typer(add_completion=False)


@app.command()
def train(
    symbol: str = typer.Option(..., help="Single symbol, e.g. BTCUSD."),
    timeframe: str = typer.Option("1h", help="Timeframe, e.g. 1h."),
    start: str = typer.Option(..., help="Start date, e.g. 2024-01-01"),
    end: str = typer.Option(..., help="End date, e.g. 2024-06-01"),
    data_dir: str | None = typer.Option(None, help="Defaults to $DATA_DIR or ./data"),
    horizon_bars: int = typer.Option(24, help="Forward-return label horizon, in bars."),
    n_splits: int = typer.Option(5, help="Number of purged K-Fold splits."),
    embargo_fraction: float = typer.Option(0.01, help="Embargo as a fraction of series length."),
    seed: int = typer.Option(42, help="Random seed for all models."),
) -> None:
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
    dataset["label_end_time"] = label["label_end_time"]
    dataset = dataset.dropna(subset=[*FEATURE_COLUMNS, "label"]).reset_index(drop=True)

    if len(dataset) < (n_splits + 1) * 10:
        log.warning("too few rows for a meaningful comparison", n_rows=len(dataset))
        return

    X = dataset[list(FEATURE_COLUMNS)]
    y = dataset["label"].to_numpy()
    folds = purged_kfold_split(
        dataset["timestamp"], dataset["label_end_time"], n_splits=n_splits,
        embargo_fraction=embargo_fraction,
    )

    log.info(
        "dataset ready",
        n_rows=len(dataset),
        positive_rate=float(y.mean()),
        n_folds=len(folds),
    )

    model_factories = {
        "naive_prior": lambda: NaivePriorBaseline(),
        "logistic_regression": lambda: LogisticRegressionModel(seed=seed),
        "random_forest": lambda: RandomForestModel(seed=seed),
        "extra_trees": lambda: ExtraTreesModel(seed=seed),
    }

    results = run_comparison(model_factories, X, y, folds)
    summary = summarize_comparison(results)
    log.info("comparison summary (mean brier ascending)", summary=summary.to_string())

    for name in ("logistic_regression", "random_forest", "extra_trees"):
        beats = beats_baseline_every_fold(results, name)
        log.info("beats naive baseline on every fold", model=name, beats=beats)

    best_model_name = summary.index[0]
    log.info("best model by mean Brier score", model=best_model_name)

    best_factory = model_factories[best_model_name]
    train_idx, test_idx = folds[-1]
    best_model = best_factory()
    best_model.fit(X.iloc[train_idx], y[train_idx])
    X_test, y_test = X.iloc[test_idx], y[test_idx]
    proba_test = best_model.predict_proba(X_test)

    curve = calibration_curve(y_test, proba_test, n_bins=10)
    log.info(
        "calibration curve (last fold)",
        bin_counts=curve.bin_counts.tolist(),
        mean_predicted=[round(v, 3) if v == v else None for v in curve.mean_predicted],
        observed_frequency=[round(v, 3) if v == v else None for v in curve.observed_frequency],
    )

    if best_model_name != "naive_prior":
        importance = permutation_importance(
            _ProbaAsPredict(best_model), X_test, y_test, brier_score, n_repeats=10, seed=seed,
            higher_is_better=False,
        )
        log.info(
            "permutation importance (last fold)",
            importance=importance.as_dataframe().to_string(),
        )


class _ProbaAsPredict:
    """Adapts a Model's predict_proba() to explainability.Predictor's
    predict() so permutation_importance can score against Brier (a
    probability-based metric) rather than the coarser hard-label accuracy.
    """

    def __init__(self, model: object) -> None:
        self._model = model

    def predict(self, X: pd.DataFrame) -> pd.Series:
        return self._model.predict_proba(X)  # type: ignore[attr-defined]


if __name__ == "__main__":
    app()
