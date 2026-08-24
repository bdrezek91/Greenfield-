"""Informal signal research: does src.engines.regime_analog_evidence's
score (empirical historical-analog win-rate, Cycle 46) have any
information content about SUBSEQUENT returns on real historical data?

Same status and caveats as
scripts/evaluate_derivatives_evidence_signal.py's own module docstring
(a lightweight sanity check, not the formal Experiment Factory; a
negative or mixed result is a valid, reportable finding per master plan
section 11.3, not something to iterate on until it looks better) - see
docs/CLAUDE_CODE_CONTINUATION.md's Cycle 49 section for this script's
first real result.

Unlike the derivatives/cross-market checks (which can compute a score
for every bar in one vectorized pass), find_historical_analogs is
inherently a POINT query (one call per query_timestamp, each one
re-scanning all eligible past candidates) - this script walks the real
history at `--stride` bars apart (default 24, i.e. once a day on 1h
bars) rather than every single bar, to keep runtime reasonable while
still producing a meaningful sample size.

Usage:
    python scripts/evaluate_regime_analog_evidence_signal.py --symbol BTCUSDT \
        --start 2024-01-01 --end 2024-06-01
"""

from __future__ import annotations

import os
from pathlib import Path

import numpy as np
import pandas as pd
import structlog
import typer
from scipy import stats

from src.data.config import load_symbol_universe
from src.data.storage import read_klines
from src.engines.regime_analog_evidence import regime_analog_family_evidence
from src.features.pipeline import build_feature_matrix
from src.regimes.analogs import AnalogFamily, AnalogSearchConfig, find_historical_analogs
from src.regimes.analogs_bridge import assemble_analog_search_frame
from src.regimes.classifier import RegimeConfig, classify_regimes

log = structlog.get_logger()
app = typer.Typer(add_completion=False)


@app.command()
def evaluate(
    symbol: str = typer.Option(..., help="Single symbol, e.g. BTCUSDT."),
    start: str = typer.Option(..., help="Start date, e.g. 2024-01-01"),
    end: str = typer.Option(..., help="End date, e.g. 2024-06-01"),
    data_dir: str | None = typer.Option(None, help="Defaults to $DATA_DIR or ./data"),
    stride: int = typer.Option(24, help="Bars between successive analog queries."),
    horizon_bars: int = typer.Option(1, help="Forward horizon to score and evaluate."),
    neighbor_count: int = typer.Option(20, help="AnalogSearchConfig.neighbor_count."),
    minimum_neighbors: int = typer.Option(10, help="AnalogSearchConfig.minimum_neighbors."),
    maximum_distance: float = typer.Option(3.0, help="AnalogSearchConfig.maximum_distance."),
) -> None:
    universe = load_symbol_universe()
    try:
        universe.validate_symbol(symbol)
    except ValueError as exc:
        raise typer.BadParameter(str(exc)) from exc
    if stride <= 0:
        raise typer.BadParameter("must be positive", param_hint="--stride")

    resolved_data_dir = Path(data_dir or os.environ.get("DATA_DIR", "./data"))
    start_ts = pd.Timestamp(start, tz="UTC")
    end_ts = pd.Timestamp(end, tz="UTC")

    df = read_klines(resolved_data_dir, symbol, "1h", start=start_ts, end=end_ts)
    if df.empty:
        log.error("no klines in range", symbol=symbol)
        raise typer.Exit(code=1)

    features = build_feature_matrix(df)[["return_1", "momentum"]]
    regime = classify_regimes(df, RegimeConfig())["trend_regime"]
    assembled = assemble_analog_search_frame(df, features, regime)
    warm = assembled.dropna(subset=["return_1", "momentum", "regime"]).reset_index(drop=True)
    if warm.empty:
        log.error("no fully-warmed-up rows in range - widen --start", symbol=symbol)
        raise typer.Exit(code=1)

    config = AnalogSearchConfig(
        families=(AnalogFamily("price", ("return_1", "momentum")),),
        horizons_bars=(horizon_bars,),
        neighbor_count=neighbor_count,
        minimum_neighbors=minimum_neighbors,
        maximum_distance=maximum_distance,
        minimum_quality_score=0.5,
        require_same_regime=False,
    )

    scores: list[float] = []
    forward_returns: list[float] = []
    price_by_ts = df.set_index("timestamp")["close"]

    for index in range(0, len(warm) - horizon_bars, stride):
        query_timestamp = warm["timestamp"].iloc[index]
        history = warm.iloc[: index + 1]
        result = find_historical_analogs(
            history,
            query_timestamp=query_timestamp,
            config=config,
            dataset_version=f"{symbol}_signal_check",
            code_version="local",
        )
        evidence = regime_analog_family_evidence(result, horizon_bars=horizon_bars)
        if evidence is None:
            continue
        future_timestamp = warm["timestamp"].iloc[index + horizon_bars]
        entry_price = price_by_ts.loc[query_timestamp]
        exit_price = price_by_ts.loc[future_timestamp]
        forward_return = float(exit_price / entry_price - 1.0)
        scores.append(evidence.score)
        forward_returns.append(forward_return)

    n = len(scores)
    if n < 5:
        log.error("too few analog queries produced usable evidence", n=n)
        raise typer.Exit(code=1)

    scores_arr = np.asarray(scores)
    returns_arr = np.asarray(forward_returns)
    ic = stats.spearmanr(scores_arr, returns_arr).correlation
    nontrivial = np.abs(scores_arr) > 0.1
    hit_rate = (
        float((np.sign(scores_arr[nontrivial]) == np.sign(returns_arr[nontrivial])).mean())
        if nontrivial.any()
        else float("nan")
    )
    log.info(
        "regime-analog evidence signal check",
        symbol=symbol,
        horizon_bars=horizon_bars,
        stride=stride,
        n=n,
        ic=round(float(ic), 4),
        hit_rate_nontrivial=round(hit_rate, 3),
        n_nontrivial=int(nontrivial.sum()),
    )


if __name__ == "__main__":
    app()
