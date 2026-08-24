"""Informal signal research: does src.engines.cross_market_evidence's
score (cross-sectional rank, Cycle 44) have any information content
about SUBSEQUENT returns for a chosen asset, on real historical data?

Same status and caveats as
scripts/evaluate_derivatives_evidence_signal.py's own module docstring
(a lightweight sanity check, not the formal Experiment Factory; a
negative or mixed result is a valid, reportable finding per master plan
section 11.3, not something to iterate on until it looks better) - see
docs/CLAUDE_CODE_CONTINUATION.md's Cycle 48 section for this script's
first real result (BTC among BTC/ETH/SOL, 2024-01-01 to 2024-06-01).

Usage:
    python scripts/evaluate_cross_market_evidence_signal.py --asset BTC \
        --universe BTC,ETH,SOL --start 2024-01-01 --end 2024-06-01
"""

from __future__ import annotations

import os
from pathlib import Path

import numpy as np
import pandas as pd
import structlog
import typer
from scipy import stats

from src.data.storage import read_klines
from src.features.cross_market import cross_market_context_frame

log = structlog.get_logger()
app = typer.Typer(add_completion=False)

_SYMBOL_BY_ASSET: dict[str, str] = {"BTC": "BTCUSDT", "ETH": "ETHUSDT", "SOL": "SOLUSDT"}


@app.command()
def evaluate(
    asset: str = typer.Option(..., help=f"Asset to score, one of {list(_SYMBOL_BY_ASSET)}."),
    universe: str = typer.Option(
        "BTC,ETH,SOL", help=f"Comma-separated universe, subset of {list(_SYMBOL_BY_ASSET)}."
    ),
    start: str = typer.Option(..., help="Start date, e.g. 2024-01-01"),
    end: str = typer.Option(..., help="End date, e.g. 2024-06-01"),
    data_dir: str | None = typer.Option(None, help="Defaults to $DATA_DIR or ./data"),
    rolling_window: int = typer.Option(20, help="cross_market_context_frame's own window."),
    dispersion_zscore_window: int = typer.Option(20, help="Dispersion z-score window."),
    horizons_bars: str = typer.Option("1,4,24", help="Comma-separated forward horizons."),
) -> None:
    assets = [item.strip().upper() for item in universe.split(",") if item.strip()]
    unknown = [item for item in assets + [asset] if item not in _SYMBOL_BY_ASSET]
    if unknown:
        raise typer.BadParameter(f"unknown asset(s) {unknown}, expected {list(_SYMBOL_BY_ASSET)}")
    if asset not in assets:
        raise typer.BadParameter("--asset must be a member of --universe")

    resolved_data_dir = Path(data_dir or os.environ.get("DATA_DIR", "./data"))
    start_ts = pd.Timestamp(start, tz="UTC")
    end_ts = pd.Timestamp(end, tz="UTC")

    rows = []
    klines_by_asset: dict[str, pd.DataFrame] = {}
    for item in assets:
        klines = read_klines(
            resolved_data_dir, _SYMBOL_BY_ASSET[item], "1h", start=start_ts, end=end_ts
        )
        if klines.empty:
            log.error("missing klines for universe member", asset=item)
            raise typer.Exit(code=1)
        klines_by_asset[item] = klines
        for _, row in klines.iterrows():
            rows.append(
                {
                    "timestamp": row["timestamp"],
                    "max_source_timestamp": row["timestamp"],
                    "asset": item,
                    "spot_price": row["close"],
                    "perpetual_price": row["close"],
                }
            )
    panel = cross_market_context_frame(pd.DataFrame(rows), rolling_window=rolling_window)
    target = (
        panel[panel["asset"] == asset].sort_values("timestamp").reset_index(drop=True)
    )

    rank = target["cross_sectional_return_rank"].astype(float)
    dispersion = target["cross_asset_return_dispersion"].astype(float)
    window = dispersion.rolling(dispersion_zscore_window, min_periods=dispersion_zscore_window)
    dispersion_zscore = (dispersion - window.mean()) / window.std(ddof=0).replace(0, np.nan)
    conviction = 1.0 / (1.0 + np.exp(-dispersion_zscore))
    score = (2.0 * (rank - 0.5) * conviction).clip(-1, 1)
    score_ungated = (2.0 * (rank - 0.5)).clip(-1, 1)

    close = (
        klines_by_asset[asset]
        .set_index("timestamp")
        .reindex(target["timestamp"])["close"]
        .reset_index(drop=True)
    )
    for horizon in (int(h) for h in horizons_bars.split(",") if h.strip()):
        forward_return = close.pct_change(horizon).shift(-horizon)
        valid = score.notna() & forward_return.notna()
        ic_gated = stats.spearmanr(score[valid], forward_return[valid]).correlation
        ic_ungated = stats.spearmanr(score_ungated[valid], forward_return[valid]).correlation
        log.info(
            "cross-market evidence signal check",
            asset=asset,
            horizon_bars=horizon,
            n=int(valid.sum()),
            ic_gated=round(float(ic_gated), 4),
            ic_ungated_no_dispersion_gate=round(float(ic_ungated), 4),
        )


if __name__ == "__main__":
    app()
