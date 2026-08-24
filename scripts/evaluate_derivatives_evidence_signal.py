"""Informal signal research: does src.engines.derivatives_evidence's
score (OI-price confirmation, Cycle 42) have any information content
about SUBSEQUENT returns on real historical data?

This is a lightweight sanity check, not the formal, preregistered
Experiment Factory (src/research/) the master plan's Research Engine
(section 11.3) describes - it exists to answer one question honestly
before anything heavier is built around this scoring rule: is there any
edge here at all. Per section 11.3 ("publish negative results and
prevent repeated mining of rejected variants") a negative or mixed
result here is a valid, useful, reportable finding, not something to
iterate on until it looks better - see
docs/CLAUDE_CODE_CONTINUATION.md's Cycle 48 section for the honest
result from this script's first real run (BTCUSDT, 2024-01-01 to
2024-06-01, using klines' close as a mark_price/index_price proxy since
no real Bybit mark/index-price history is downloaded by this project -
a documented simplification of this check, not of the evidence function
itself).

Usage:
    python scripts/evaluate_derivatives_evidence_signal.py --symbol BTCUSDT \
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
from src.data.storage import read_funding, read_klines, read_open_interest
from src.features.derivatives import derivatives_context_frame

log = structlog.get_logger()
app = typer.Typer(add_completion=False)


@app.command()
def evaluate(
    symbol: str = typer.Option(..., help="Single symbol, e.g. BTCUSDT."),
    start: str = typer.Option(..., help="Start date, e.g. 2024-01-01"),
    end: str = typer.Option(..., help="End date, e.g. 2024-06-01"),
    data_dir: str | None = typer.Option(None, help="Defaults to $DATA_DIR or ./data"),
    zscore_window: int = typer.Option(20, help="mark_return rolling z-score window."),
    horizons_bars: str = typer.Option("1,4,24", help="Comma-separated forward horizons."),
) -> None:
    universe = load_symbol_universe()
    try:
        universe.validate_symbol(symbol)
    except ValueError as exc:
        raise typer.BadParameter(str(exc)) from exc

    resolved_data_dir = Path(data_dir or os.environ.get("DATA_DIR", "./data"))
    start_ts = pd.Timestamp(start, tz="UTC")
    end_ts = pd.Timestamp(end, tz="UTC")

    klines = read_klines(resolved_data_dir, symbol, "1h", start=start_ts, end=end_ts)
    oi = read_open_interest(resolved_data_dir, symbol, "1h", start=start_ts, end=end_ts)
    funding = read_funding(resolved_data_dir, symbol, start=start_ts, end=end_ts)
    if klines.empty or oi.empty or funding.empty:
        log.error("missing klines/open-interest/funding for the requested range", symbol=symbol)
        raise typer.Exit(code=1)

    merged = klines[["timestamp", "close"]].merge(
        oi[["timestamp", "open_interest"]], on="timestamp", how="inner"
    )
    merged = pd.merge_asof(
        merged.sort_values("timestamp"),
        funding.sort_values("timestamp")[["timestamp", "funding_rate"]],
        on="timestamp",
        direction="backward",
    ).dropna()
    if merged.empty:
        log.error("no overlapping klines/OI/funding rows", symbol=symbol)
        raise typer.Exit(code=1)

    raw = pd.DataFrame(
        {
            "timestamp": merged["timestamp"],
            "max_source_timestamp": merged["timestamp"],
            # No real Bybit mark/index-price history is downloaded by
            # this project - close is used for both as a documented
            # proxy (see this script's own module docstring).
            "mark_price": merged["close"],
            "index_price": merged["close"],
            "open_interest": merged["open_interest"],
            "funding_rate": merged["funding_rate"],
        }
    )
    context = derivatives_context_frame(raw, rolling_window=zscore_window)

    mark_return = context["mark_return"].astype(float)
    window = mark_return.rolling(zscore_window, min_periods=zscore_window)
    zscore = (mark_return - window.mean()) / window.std(ddof=0).replace(0, np.nan)
    oi_confirmation = context["oi_price_confirmation"]
    conviction = np.where(oi_confirmation > 0, 1.0, np.where(oi_confirmation < 0, 0.0, 0.5))
    score = pd.Series(np.tanh(zscore) * conviction, index=context.index)
    score_ungated = pd.Series(np.tanh(zscore), index=context.index)

    close = merged["close"].reset_index(drop=True)
    for horizon in (int(h) for h in horizons_bars.split(",") if h.strip()):
        forward_return = close.pct_change(horizon).shift(-horizon)
        valid = score.notna() & forward_return.notna()
        ic_gated = stats.spearmanr(score[valid], forward_return[valid]).correlation
        ic_ungated = stats.spearmanr(score_ungated[valid], forward_return[valid]).correlation
        confirmed = valid & (pd.Series(conviction) == 1.0) & (score.abs() > 0.1)
        hit_rate = (
            (np.sign(score[confirmed]) == np.sign(forward_return[confirmed])).mean()
            if confirmed.any()
            else float("nan")
        )
        log.info(
            "derivatives evidence signal check",
            symbol=symbol,
            horizon_bars=horizon,
            n=int(valid.sum()),
            ic_gated=round(float(ic_gated), 4),
            ic_ungated_no_oi_gate=round(float(ic_ungated), 4),
            hit_rate_confirmed_nontrivial=round(float(hit_rate), 3),
            n_confirmed=int(confirmed.sum()),
        )


if __name__ == "__main__":
    app()
