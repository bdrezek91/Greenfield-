"""Exploratory diagnostics for collected microstructure data - data quality
and coverage, plus an ORIENTING (not a backtest) check of whether top-of-
book imbalance has any relationship with the next bar's return.

This is deliberately NOT a strategy and does not go through
src/research/ - family E (microstructure) is disabled in
configs/research_protocol.yaml until there is enough history to trust
any result from it (see that file's comment and
docs/PROJECT_STATUS.md). Running this script, looking at a correlation
number, and treating it as a finding would be exactly the kind of
single-look, no-multiple-testing-correction, no-cost-model conclusion the
whole research protocol exists to prevent. Its only job is to answer
"is there enough here to bother investing in a real feature pipeline and
strategy", not "here is an edge".

No slippage/fees/spread-crossing cost is modeled here at all - a real
signal at this frequency also has to survive execution cost, which this
script makes zero attempt to estimate.

Usage:
    python scripts/explore_microstructure.py --symbol BTCUSDT --bar-seconds 60
"""

from __future__ import annotations

import os
from pathlib import Path

import numpy as np
import pandas as pd
import structlog
import typer

from src.data.microstructure_writer import read_range

log = structlog.get_logger()
app = typer.Typer(add_completion=False)


def _coverage_report(df: pd.DataFrame, stream: str, gap_threshold_seconds: float) -> dict:
    if df.empty:
        return {"stream": stream, "rows": 0}
    ts = df["timestamp"].sort_values()
    gaps = ts.diff().dt.total_seconds().dropna()
    return {
        "stream": stream,
        "rows": len(df),
        "start": str(ts.iloc[0]),
        "end": str(ts.iloc[-1]),
        "duplicate_timestamps": int(ts.duplicated().sum()),
        "median_gap_seconds": float(gaps.median()) if not gaps.empty else None,
        "max_gap_seconds": float(gaps.max()) if not gaps.empty else None,
        "gaps_over_threshold": int((gaps > gap_threshold_seconds).sum()),
    }


@app.command()
def explore(
    symbol: str = typer.Option(..., help="e.g. BTCUSDT"),
    data_dir: str | None = typer.Option(None, help="Defaults to $DATA_DIR or ./data"),
    bar_seconds: int = typer.Option(60, help="Aggregation window for the orienting check."),
    gap_threshold_seconds: float = typer.Option(
        5.0, help="A gap longer than this between consecutive updates is flagged."
    ),
) -> None:
    resolved_data_dir = Path(data_dir or os.environ.get("DATA_DIR", "./data"))
    micro_dir = resolved_data_dir / "microstructure"
    orderbook_dir = micro_dir / "orderbook" / symbol
    trades_dir = micro_dir / "trades" / symbol
    if not orderbook_dir.exists() or not trades_dir.exists():
        log.error("no microstructure data on disk for this symbol", symbol=symbol)
        raise typer.Exit(code=1)

    # Wide enough to cover everything collected so far - read_range filters
    # to what actually exists, this is just an upper bound.
    start = pd.Timestamp.now(tz="UTC") - pd.Timedelta(days=365)
    end = pd.Timestamp.now(tz="UTC")

    orderbook = read_range(resolved_data_dir, "orderbook", symbol, start, end)
    trades = read_range(resolved_data_dir, "trades", symbol, start, end)

    log.info(
        "=== coverage: orderbook ===",
        **_coverage_report(orderbook, "orderbook", gap_threshold_seconds),
    )
    log.info(
        "=== coverage: trades ===", **_coverage_report(trades, "trades", gap_threshold_seconds)
    )

    if orderbook.empty or trades.empty:
        log.warning("not enough data for the orienting check - stopping here")
        raise typer.Exit(code=0)

    # Aggregate to fixed bars: mean top-of-book imbalance, last trade price
    # (a simple close proxy) - never look inside a bar to decide that bar's
    # own imbalance-vs-return relationship.
    ob = orderbook.set_index("timestamp").sort_index()
    tr = trades.set_index("timestamp").sort_index()
    freq = f"{bar_seconds}s"
    imbalance_bars = ob["imbalance"].resample(freq).mean()
    spread_bars = ob["spread"].resample(freq).mean()
    price_bars = tr["price"].resample(freq).last().ffill()
    trade_count_bars = tr["price"].resample(freq).count()

    # Trade-flow imbalance: net taker aggression from the trades stream
    # (who actually paid the spread to trade), as opposed to top-of-book
    # imbalance (who is merely resting size, which can be pulled without
    # ever trading) - a different, and arguably more direct, proxy for
    # near-term buying/selling pressure.
    # Bybit's raw taker-side field is "Buy"/"Sell" (see
    # src/data/microstructure_parser.py's parse_trade_message), not
    # "BUY"/"SELL" - match case-insensitively so this doesn't silently
    # match nothing (which would zero out every bar's volume here, not
    # error) if that raw casing ever changes.
    side_upper = tr["side"].str.upper()
    buy_volume = tr.loc[side_upper == "BUY", "size"].resample(freq).sum()
    sell_volume = tr.loc[side_upper == "SELL", "size"].resample(freq).sum()
    total_volume = (buy_volume.add(sell_volume, fill_value=0.0)).replace(0.0, np.nan)
    trade_flow_bars = (buy_volume.subtract(sell_volume, fill_value=0.0)) / total_volume

    combined = pd.DataFrame(
        {
            "imbalance": imbalance_bars,
            "trade_flow_imbalance": trade_flow_bars,
            "spread": spread_bars,
            "price": price_bars,
            "trade_count": trade_count_bars,
        }
    ).dropna()
    # Imbalance momentum: change in top-of-book imbalance, not its level -
    # a third candidate feature, computed only from bars already in
    # `combined` so it needs no separate NaN handling below.
    combined["imbalance_delta"] = combined["imbalance"].diff()
    combined["forward_return"] = combined["price"].pct_change().shift(-1)
    combined = combined.dropna()

    if len(combined) < 30:
        log.warning(
            "too few aggregated bars for a meaningful correlation check",
            n_bars=len(combined),
        )
        raise typer.Exit(code=0)

    candidate_features = ("imbalance", "trade_flow_imbalance", "imbalance_delta")
    correlations = {
        feature: float(np.corrcoef(combined[feature], combined["forward_return"])[0, 1])
        for feature in candidate_features
    }
    positive_fraction = float((combined["forward_return"] > 0).mean())

    log.info(
        "=== orienting check (NOT a backtest, NOT a finding) ===",
        n_bars=len(combined),
        bar_seconds=bar_seconds,
        **{f"{k}_vs_next_bar_return_correlation": round(v, 4) for k, v in correlations.items()},
        fraction_of_bars_with_positive_forward_return=round(positive_fraction, 4),
        mean_trades_per_bar=round(float(combined["trade_count"].mean()), 1),
        mean_spread=round(float(combined["spread"].mean()), 6),
    )
    log.warning(
        "reminder: no execution costs modeled, single short sample, no "
        "multiple-testing correction, no walk-forward split, and checking "
        "three candidate features here already means any one of them "
        "looking best is partly luck - this answers 'is it worth "
        "collecting more data and building this properly', not 'is there "
        "an edge', for ANY of the three"
    )


if __name__ == "__main__":
    app()
