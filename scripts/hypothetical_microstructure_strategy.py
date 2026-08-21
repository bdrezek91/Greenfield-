"""One-off, explicitly-authorized hypothetical backtest of an order-book-
imbalance day-trading idea on the small amount of real microstructure data
collected so far.

THIS IS NOT A PROMOTION-ELIGIBLE STRATEGY. It exists outside
src/research/ entirely: it is not registered in src/strategies/registry.py,
it does not go through the walk-forward/DSR/PBO/promotion-gate pipeline,
and it does not touch configs/research_protocol.yaml (family E -
microstructure - stays disabled there). Running it and looking at a
"looks profitable" number is exactly the single-look, no-multiple-testing-
correction mistake the whole research protocol exists to prevent.

It was written on the user's explicit, one-time request to see what a
naive version of this idea does on the ~17 hours of BTCUSDT order-book/
trade data collected so far, fully aware that:
  - one symbol, ~17h is nowhere near enough to draw any conclusion,
  - there is no purge/embargo between the "train" (threshold-picking) and
    "test" (evaluation) halves, only a chronological split,
  - no walk-forward, no DSR, no PBO, no perturbation/entry-lag robustness,
  - no promotion path exists for whatever this prints.

Signal: naive imbalance threshold. If mean top-of-book imbalance over the
past N bars exceeds +threshold, go long for exactly one bar; below
-threshold, go short for one bar; otherwise flat. Costs: taker fee
(configs/instruments.yaml) charged twice (entry+exit) plus half the mean
spread crossed on each side, both real numbers pulled from the same
collected data - not an assumption.

Usage:
    python scripts/hypothetical_microstructure_strategy.py --symbol BTCUSDT --bar-seconds 60
"""

from __future__ import annotations

import os
from pathlib import Path

import numpy as np
import pandas as pd
import structlog
import typer
import yaml

from src.data.microstructure_writer import read_range

log = structlog.get_logger()
app = typer.Typer(add_completion=False)

_PERIODS_PER_YEAR_AT_1S = 365 * 24 * 60 * 60


def _load_taker_fee(config_path: Path) -> float:
    with config_path.open(encoding="utf-8") as f:
        raw = yaml.safe_load(f)
    # configs/instruments.yaml keys the fee schedule under a shared default
    # block used by every instrument - read it the same way the rest of the
    # codebase does rather than hardcoding 0.00055 here.
    for section in raw.values():
        if isinstance(section, dict) and "taker_fee" in section:
            return float(section["taker_fee"])
    raise ValueError(f"no taker_fee found in {config_path}")


def _build_bars(orderbook: pd.DataFrame, trades: pd.DataFrame, bar_seconds: int) -> pd.DataFrame:
    ob = orderbook.set_index("timestamp").sort_index()
    tr = trades.set_index("timestamp").sort_index()
    freq = f"{bar_seconds}s"
    bars = pd.DataFrame(
        {
            "imbalance": ob["imbalance"].resample(freq).mean(),
            "spread": ob["spread"].resample(freq).mean(),
            "price": tr["price"].resample(freq).last().ffill(),
            "trade_count": tr["price"].resample(freq).count(),
        }
    ).dropna()
    return bars


def _apply_signal(bars: pd.DataFrame, lookback_bars: int, threshold: float) -> pd.DataFrame:
    bars = bars.copy()
    bars["signal_input"] = bars["imbalance"].rolling(lookback_bars).mean()
    bars["position"] = 0
    bars.loc[bars["signal_input"] > threshold, "position"] = 1
    bars.loc[bars["signal_input"] < -threshold, "position"] = -1
    # Hold for exactly one bar: next bar's return, position decided on this
    # bar's close using only this-and-earlier bars' imbalance (no look-ahead).
    bars["bar_return"] = bars["price"].pct_change().shift(-1)
    return bars.dropna(subset=["signal_input", "bar_return"])


def _evaluate(bars: pd.DataFrame, taker_fee: float, bar_seconds: int, label: str) -> dict:
    traded = bars[bars["position"] != 0]
    if traded.empty:
        log.warning(f"=== {label}: no trades at this threshold ===")
        return {"label": label, "n_trades": 0}

    gross_return = traded["position"] * traded["bar_return"]
    # Cost per round trip: taker fee charged on entry and exit, plus half
    # the mean spread crossed on each side - both real, measured numbers,
    # not assumptions layered on top of the raw signal.
    half_spread_frac = (traded["spread"] / 2) / traded["price"]
    cost_per_trade = 2 * taker_fee + 2 * half_spread_frac
    net_return = gross_return - cost_per_trade

    periods_per_year = _PERIODS_PER_YEAR_AT_1S / bar_seconds
    mean_net = float(net_return.mean())
    std_net = float(net_return.std())
    sharpe = (mean_net / std_net) * float(np.sqrt(periods_per_year)) if std_net > 0 else 0.0

    result = {
        "label": label,
        "n_trades": int(len(traded)),
        "gross_total_return": round(float(gross_return.sum()), 6),
        "net_total_return_after_costs": round(float(net_return.sum()), 6),
        "mean_net_return_per_trade": round(mean_net, 8),
        "fraction_of_trades_net_positive": round(float((net_return > 0).mean()), 4),
        "naive_sharpe_not_deflated": round(sharpe, 4),
    }
    log.info(f"=== {label} ===", **result)
    return result


@app.command()
def run(
    symbol: str = typer.Option(..., help="e.g. BTCUSDT"),
    data_dir: str | None = typer.Option(None, help="Defaults to $DATA_DIR or ./data"),
    instruments_config: str = typer.Option("configs/instruments.yaml"),
    bar_seconds: int = typer.Option(60, help="Bar aggregation window."),
    lookback_bars: int = typer.Option(5, help="Rolling mean-imbalance window for the signal."),
    threshold: float = typer.Option(0.1, help="Imbalance threshold to go long/short."),
    train_fraction: float = typer.Option(
        0.5, help="Chronological split point - NOT a purged/embargoed walk-forward split."
    ),
) -> None:
    log.warning(
        "HYPOTHETICAL, ONE-OFF EXPERIMENT - not part of src/research/, not "
        "promotion-eligible, ~17h single-symbol sample. See module "
        "docstring before drawing any conclusion from this output."
    )
    resolved_data_dir = Path(data_dir or os.environ.get("DATA_DIR", "./data"))
    orderbook = read_range(
        resolved_data_dir,
        "orderbook",
        symbol,
        pd.Timestamp.now(tz="UTC") - pd.Timedelta(days=365),
        pd.Timestamp.now(tz="UTC"),
    )
    trades = read_range(
        resolved_data_dir,
        "trades",
        symbol,
        pd.Timestamp.now(tz="UTC") - pd.Timedelta(days=365),
        pd.Timestamp.now(tz="UTC"),
    )
    if orderbook.empty or trades.empty:
        log.error("no microstructure data on disk for this symbol", symbol=symbol)
        raise typer.Exit(code=1)

    bars = _build_bars(orderbook, trades, bar_seconds)
    if len(bars) < 30:
        log.warning("too few aggregated bars to evaluate anything", n_bars=len(bars))
        raise typer.Exit(code=0)

    signalled = _apply_signal(bars, lookback_bars, threshold)
    taker_fee = _load_taker_fee(Path(instruments_config))

    split_idx = int(len(signalled) * train_fraction)
    first_half = signalled.iloc[:split_idx]
    second_half = signalled.iloc[split_idx:]

    log.info(
        "chronological split (NOT purged/embargoed walk-forward)",
        n_bars_total=len(signalled),
        n_bars_first_half=len(first_half),
        n_bars_second_half=len(second_half),
    )
    _evaluate(first_half, taker_fee, bar_seconds, "first half (in-sample-ish)")
    _evaluate(second_half, taker_fee, bar_seconds, "second half (out-of-sample-ish)")
    _evaluate(signalled, taker_fee, bar_seconds, "full sample")

    log.warning(
        "reminder: single symbol, ~17h of data, no walk-forward, no DSR, "
        "no PBO, no perturbation/entry-lag robustness, no multiple-testing "
        "correction across (lookback_bars, threshold, bar_seconds) choices. "
        "This is an orienting number for a one-off question, not evidence "
        "of an edge, and nothing in this repo will promote it."
    )


if __name__ == "__main__":
    app()
