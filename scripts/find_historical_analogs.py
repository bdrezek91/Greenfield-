"""CLI to find historical analogs for the current (or a given) market
state - the CLI consumer Cycle 38's src.regimes.analogs_bridge flagged
as not yet built ("no strategy/script consumes this yet").

Builds the analog search space entirely from klines: build_feature_matrix
for the feature columns, classify_regimes's `trend_regime` for the
regime label (the simplest, single-domain classifier - a caller wanting
Cycle 37's richer multidomain regimes, or multiple weighted feature
families instead of this CLI's single one, should call
src.regimes.analogs_bridge.assemble_analog_search_frame /
src.regimes.analogs.find_historical_analogs directly; this CLI is a
convenient single-family default entry point, not the only way to use
either).

find_historical_analogs' own "fail closed on any non-finite value across
the whole frame" contract (see src/regimes/analogs_bridge.py's module
docstring) means the requested date range must be long enough that every
chosen --feature-columns entry has matured well before its end - this
CLI trims the leading NaN rows for you (documented below), unlike the
bridge function itself, since here there is no ambiguity about "warmup
vs. a real data gap": klines read from src.data.storage.read_klines are
either present or the range is simply too short, and either way failing
loudly with a clear reason is what happens if trimming still leaves too
little history for find_historical_analogs' own embargo/neighbor
requirements.

Usage:
    python scripts/find_historical_analogs.py --symbol BTCUSDT --timeframe 1h \
        --start 2024-01-01 --end 2024-06-01 \
        --feature-columns return_1,momentum,atr,realized_vol
"""

from __future__ import annotations

import os
from pathlib import Path

import pandas as pd
import structlog
import typer

from src.data.config import load_symbol_universe
from src.data.storage import read_klines
from src.features.pipeline import build_feature_matrix
from src.regimes.analogs import AnalogFamily, AnalogSearchConfig, find_historical_analogs
from src.regimes.analogs_bridge import assemble_analog_search_frame
from src.regimes.classifier import classify_regimes

log = structlog.get_logger()
app = typer.Typer(add_completion=False)


@app.command()
def find(
    symbol: str = typer.Option(..., help="Single symbol, e.g. BTCUSDT."),
    timeframe: str = typer.Option("1h", help="Timeframe, e.g. 1h."),
    start: str = typer.Option(..., help="Start date, e.g. 2024-01-01"),
    end: str = typer.Option(..., help="End date, e.g. 2024-06-01"),
    feature_columns: str = typer.Option(
        "return_1,momentum,atr,realized_vol",
        help="Comma-separated build_feature_matrix columns forming the one analog family.",
    ),
    query_timestamp: str | None = typer.Option(
        None, help="Defaults to the last available bar in the range."
    ),
    horizons_bars: str = typer.Option("1,6,24", help="Comma-separated forward horizons, in bars."),
    neighbor_count: int = typer.Option(20, help="Target number of non-overlapping neighbors."),
    minimum_neighbors: int = typer.Option(10, help="Minimum neighbors required to be meaningful."),
    maximum_distance: float = typer.Option(3.0, help="Maximum standardized distance to qualify."),
    minimum_quality_score: float = typer.Option(0.8, help="Minimum per-bar data quality score."),
    require_same_regime: bool = typer.Option(
        True, help="Restrict candidates to the query's own trend_regime."
    ),
    data_dir: str | None = typer.Option(None, help="Defaults to $DATA_DIR or ./data"),
) -> None:
    universe = load_symbol_universe()
    try:
        universe.validate_symbol(symbol)
        universe.validate_timeframe(timeframe)
    except ValueError as exc:
        raise typer.BadParameter(str(exc)) from exc

    columns = tuple(c.strip() for c in feature_columns.split(",") if c.strip())
    if not columns:
        raise typer.BadParameter("must name at least one column", param_hint="--feature-columns")
    horizons = tuple(int(h.strip()) for h in horizons_bars.split(",") if h.strip())

    resolved_data_dir = Path(data_dir or os.environ.get("DATA_DIR", "./data"))
    start_ts = pd.Timestamp(start, tz="UTC")
    end_ts = pd.Timestamp(end, tz="UTC")

    klines = read_klines(resolved_data_dir, symbol, timeframe, start=start_ts, end=end_ts)
    if klines.empty:
        log.error("no klines in range", symbol=symbol, timeframe=timeframe)
        raise typer.Exit(code=1)

    features = build_feature_matrix(klines)[list(columns)]
    regime = classify_regimes(klines)["trend_regime"]
    assembled = assemble_analog_search_frame(klines, features, regime)

    # Trim leading warmup rows - find_historical_analogs requires the
    # WHOLE frame finite in the chosen feature columns (see this script's
    # own module docstring).
    warm_mask = assembled[list(columns)].notna().all(axis=1) & assembled["regime"].notna()
    if not warm_mask.any():
        log.error("no fully-warmed-up rows in range - widen --start", symbol=symbol)
        raise typer.Exit(code=1)
    warm = assembled.loc[warm_mask].reset_index(drop=True)

    query = (
        pd.Timestamp(query_timestamp, tz="UTC")
        if query_timestamp is not None
        else warm["timestamp"].iloc[-1]
    )
    config = AnalogSearchConfig(
        families=(AnalogFamily("price_technical", columns),),
        horizons_bars=horizons,
        neighbor_count=neighbor_count,
        minimum_neighbors=minimum_neighbors,
        maximum_distance=maximum_distance,
        minimum_quality_score=minimum_quality_score,
        require_same_regime=require_same_regime,
    )

    result = find_historical_analogs(
        warm,
        query_timestamp=query,
        config=config,
        dataset_version=f"{symbol}_{timeframe}_{start}_{end}",
        code_version="local",
    )

    log.info(
        "historical analog search",
        symbol=symbol,
        query_timestamp=str(result.query_timestamp_utc),
        regime=result.regime,
        is_meaningful=result.is_meaningful,
        warning=result.warning,
        eligible_candidate_count=result.eligible_candidate_count,
        neighbor_count=len(result.neighbors),
    )
    for horizon, distribution in sorted(result.distributions.items()):
        log.info(
            "analog forward-return distribution",
            horizon_bars=horizon,
            sample_size=distribution.sample_size,
            mean_return=round(distribution.mean_return, 5),
            median_return=round(distribution.median_return, 5),
            positive_probability=round(distribution.positive_probability, 3),
            adverse_return_q10=round(distribution.adverse_return_q10, 5),
            favorable_return_q90=round(distribution.favorable_return_q90, 5),
        )


if __name__ == "__main__":
    app()
