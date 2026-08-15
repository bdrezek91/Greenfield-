"""Run several strategies on the same data/costs and compare them fairly.

This is the "framework for fair comparison" required by
docs/RESEARCH_METHODOLOGY.md and docs/PHASE_0_ARCHITECTURE_RESEARCH.md
section 11: every strategy runs through the same engine, the same cost
model, and (for everything but Buy & Hold) the same fixed-fraction sizing/
holding-period rule (src/strategies/base.py) - only the entry signal
differs. Each run is recorded as an experiment.

Comparing multiple strategies at once is exactly the scenario
docs/RESEARCH_METHODOLOGY.md's multiple-testing section warns about: some
will look good by chance. For every strategy beyond the mandatory
benchmarks, this script also reports the Deflated Sharpe Ratio
(src/analytics/robustness.py) against `n_trials` = the number of strategies
compared in this run - a rough, session-local selection-bias check, not a
substitute for the fuller roadmap in that section.

Usage:
    python scripts/compare_strategies.py --symbol BTCUSDT --timeframe 1h \
        --start 2024-01-01 --end 2024-03-01
    python scripts/compare_strategies.py --symbol BTCUSDT --start 2024-01-01 \
        --end 2024-03-01 --strategies trend_following,momentum,breakout
"""

from __future__ import annotations

import os
from decimal import Decimal
from pathlib import Path

import pandas as pd
import structlog
import typer

from src.analytics.experiment import ExperimentStore, capture_git_commit, fingerprint_dataset
from src.analytics.robustness import deflated_sharpe_ratio
from src.backtesting.runner import run_and_record
from src.data.config import load_symbol_universe
from src.strategies.registry import ALL_STRATEGIES, BENCHMARK_STRATEGIES

log = structlog.get_logger()
app = typer.Typer(add_completion=False)


@app.command()
def compare(
    symbol: str = typer.Option(..., help="Single symbol, e.g. BTCUSDT."),
    timeframe: str = typer.Option("1h", help="Timeframe, e.g. 1h."),
    start: str = typer.Option(..., help="Start date, e.g. 2024-01-01"),
    end: str = typer.Option(..., help="End date, e.g. 2024-02-01"),
    data_dir: str | None = typer.Option(None, help="Defaults to $DATA_DIR or ./data"),
    starting_balance: float = typer.Option(100_000.0, help="Starting USDT balance."),
    periods_per_year: float = typer.Option(
        365.25 * 24, help="For annualizing Sharpe/Sortino; defaults to hourly bars."
    ),
    strategies: str = typer.Option(
        ",".join(ALL_STRATEGIES),
        help="Comma-separated strategy names to compare.",
    ),
) -> None:
    universe = load_symbol_universe()
    try:
        universe.validate_symbol(symbol)
        universe.validate_timeframe(timeframe)
    except ValueError as exc:
        raise typer.BadParameter(str(exc)) from exc

    names = [s.strip() for s in strategies.split(",") if s.strip()]
    unknown = [n for n in names if n not in ALL_STRATEGIES]
    if unknown:
        raise typer.BadParameter(
            f"unknown strategies {unknown}, expected some of {list(ALL_STRATEGIES)}",
            param_hint="--strategies",
        )

    resolved_data_dir = Path(data_dir or os.environ.get("DATA_DIR", "./data"))
    start_ts = pd.Timestamp(start, tz="UTC")
    end_ts = pd.Timestamp(end, tz="UTC")
    store = ExperimentStore()
    repo_root = Path(__file__).resolve().parents[1]
    git_commit = capture_git_commit(repo_root)
    dataset_version = fingerprint_dataset(resolved_data_dir, symbol, timeframe)

    results = []
    for name in names:
        strategy_cls, config_cls = ALL_STRATEGIES[name]
        result = run_and_record(
            name=name,
            strategy_cls=strategy_cls,
            config_cls=config_cls,
            symbol=symbol,
            timeframe=timeframe,
            start=start_ts,
            end=end_ts,
            data_dir=resolved_data_dir,
            starting_balance=Decimal(str(starting_balance)),
            periods_per_year=periods_per_year,
            store=store,
            git_commit=git_commit,
            dataset_version=dataset_version,
        )
        results.append(result)

        dsr = None
        if name not in BENCHMARK_STRATEGIES:
            returns = result.equity.pct_change().dropna()
            if len(returns) >= 2 and returns.std(ddof=1) > 0:
                # Per-period (unannualized) Sharpe, matching returns' own
                # period - deflated_sharpe_ratio's math saturates to ~1.0 if
                # given the annualized Sharpe against per-period returns
                # (see the scale-mismatch note in src/analytics/robustness.py).
                per_period_sharpe = returns.mean() / returns.std(ddof=1)
                dsr = deflated_sharpe_ratio(
                    per_period_sharpe, returns, n_trials=len(names)
                ).deflated_sharpe_ratio

        log.info(
            "strategy finished",
            strategy=name,
            experiment_id=result.experiment_id,
            trades=result.metrics.trade_metrics.trades,
            net_return=round(result.metrics.trade_metrics.net_return, 2),
            sharpe=result.metrics.equity_metrics.sharpe,
            max_drawdown=result.metrics.equity_metrics.max_drawdown,
            deflated_sharpe_ratio=dsr,
        )

    random_entry_sharpe = next(
        (r.metrics.equity_metrics.sharpe for r in results if r.name == "random_entry"), None
    )
    if random_entry_sharpe is not None:
        for r in results:
            if r.name in BENCHMARK_STRATEGIES:
                continue
            beat_random = r.metrics.equity_metrics.sharpe > random_entry_sharpe
            log.info(
                "vs. random entry",
                strategy=r.name,
                beats_random_entry_sharpe=beat_random,
            )

    log.info(
        "comparison finished",
        strategies=names,
        experiment_ids=[r.experiment_id for r in results],
    )


if __name__ == "__main__":
    app()
