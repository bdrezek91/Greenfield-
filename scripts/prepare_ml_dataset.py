"""CLI demonstrating the Phase 11 ML research framework end to end: load
klines -> build features -> build a label -> purged/embargoed split.

No model is trained here - that's Phase 12 (see src/ml/baseline.py). This
proves the framework's pieces compose correctly on real data.

Usage:
    python scripts/prepare_ml_dataset.py --symbol BTCUSD --timeframe 1h \
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
from src.ml.labels import forward_return_label
from src.ml.splits import purged_kfold_split

log = structlog.get_logger()
app = typer.Typer(add_completion=False)


@app.command()
def prepare(
    symbol: str = typer.Option(..., help="Single symbol, e.g. BTCUSD."),
    timeframe: str = typer.Option("1h", help="Timeframe, e.g. 1h."),
    start: str = typer.Option(..., help="Start date, e.g. 2024-01-01"),
    end: str = typer.Option(..., help="End date, e.g. 2024-06-01"),
    data_dir: str | None = typer.Option(None, help="Defaults to $DATA_DIR or ./data"),
    horizon_bars: int = typer.Option(24, help="Forward-return label horizon, in bars."),
    n_splits: int = typer.Option(5, help="Number of purged K-Fold splits."),
    embargo_fraction: float = typer.Option(0.01, help="Embargo as a fraction of series length."),
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
    dataset["label"] = label["label"]
    dataset["label_end_time"] = label["label_end_time"]
    n_before = len(dataset)
    dataset = dataset.dropna(subset=[*FEATURE_COLUMNS, "label"]).reset_index(drop=True)

    log.info(
        "dataset prepared",
        symbol=symbol,
        rows_total=n_before,
        rows_after_dropna=len(dataset),
        n_features=len(FEATURE_COLUMNS),
        label_mean=float(dataset["label"].mean()) if not dataset.empty else None,
        label_std=float(dataset["label"].std()) if not dataset.empty else None,
    )
    if dataset.empty:
        log.warning("no rows left after dropping NaN feature/label rows - date range too short")
        return

    folds = purged_kfold_split(
        dataset["timestamp"], dataset["label_end_time"], n_splits=n_splits,
        embargo_fraction=embargo_fraction,
    )
    for i, (train_idx, test_idx) in enumerate(folds):
        log.info(
            "fold prepared",
            fold=i,
            train_rows=len(train_idx),
            test_rows=len(test_idx),
            purged_rows=len(dataset) - len(train_idx) - len(test_idx),
        )


if __name__ == "__main__":
    app()
