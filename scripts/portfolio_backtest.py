"""CLI to backtest one strategy independently across several symbols and
aggregate the results into portfolio-level metrics.

See src/portfolio/aggregation.py's docstring for the scope boundary: each
symbol is backtested independently (its own account/risk budget), then
combined post-hoc - not one simultaneous multi-instrument strategy sharing
a single live risk budget.

Usage:
    python scripts/portfolio_backtest.py --strategy trend_following \
        --symbols BTCUSDT,ETHUSDT,SOLUSDT --timeframe 1h \
        --start 2024-01-01 --end 2024-06-01
"""

from __future__ import annotations

import os
from decimal import Decimal
from pathlib import Path

import numpy as np
import pandas as pd
import structlog
import typer

from src.analytics.experiment import ExperimentRecord, ExperimentStore, capture_git_commit
from src.analytics.report import save_report
from src.backtesting.annualization import resolve_periods_per_year
from src.backtesting.funding import FundingAssumptions
from src.backtesting.runner import run_backtest_window
from src.data.config import load_symbol_universe
from src.portfolio.aggregation import (
    SymbolResult,
    combine_equity_curves,
    concentration_hhi,
    correlation_matrix,
    portfolio_drawdown,
    portfolio_exposure,
)
from src.strategies.registry import ALL_STRATEGIES

log = structlog.get_logger()
app = typer.Typer(add_completion=False)


@app.command()
def portfolio_backtest(
    symbols: str = typer.Option(..., help="Comma-separated symbols, e.g. BTCUSDT,ETHUSDT."),
    timeframe: str = typer.Option("1h", help="Timeframe, e.g. 1h."),
    strategy: str = typer.Option(..., help=f"One of {list(ALL_STRATEGIES)}."),
    start: str = typer.Option(..., help="Start date, e.g. 2024-01-01"),
    end: str = typer.Option(..., help="End date, e.g. 2024-06-01"),
    data_dir: str | None = typer.Option(None, help="Defaults to $DATA_DIR or ./data"),
    starting_balance: float = typer.Option(
        100_000.0, help="Starting USDT balance PER symbol (see module docstring)."
    ),
    periods_per_year: float | None = typer.Option(
        None,
        help=(
            "For annualizing Sharpe/Sortino/Calmar. Defaults to the value "
            "implied by --timeframe; pass this to override."
        ),
    ),
    apply_funding: bool = typer.Option(
        True, help="Charge perpetual funding against every trade (see run_walk_forward.py)."
    ),
) -> None:
    universe = load_symbol_universe()
    symbol_list = [s.strip() for s in symbols.split(",") if s.strip()]
    for symbol in symbol_list:
        try:
            universe.validate_symbol(symbol)
        except ValueError as exc:
            raise typer.BadParameter(str(exc), param_hint="--symbols") from exc
    try:
        universe.validate_timeframe(timeframe)
    except ValueError as exc:
        raise typer.BadParameter(str(exc), param_hint="--timeframe") from exc
    if strategy not in ALL_STRATEGIES:
        raise typer.BadParameter(
            f"unknown strategy {strategy!r}, expected one of {list(ALL_STRATEGIES)}",
            param_hint="--strategy",
        )

    resolved_data_dir = Path(data_dir or os.environ.get("DATA_DIR", "./data"))
    start_ts = pd.Timestamp(start, tz="UTC")
    end_ts = pd.Timestamp(end, tz="UTC")
    strategy_cls, config_cls = ALL_STRATEGIES[strategy]
    resolved_periods_per_year, periods_per_year_source = resolve_periods_per_year(
        timeframe, periods_per_year
    )
    funding_assumptions = FundingAssumptions() if apply_funding else None

    results: list[SymbolResult] = []
    funding_applied_all = True
    mark_to_market_applied_all = True
    for symbol in symbol_list:
        window = run_backtest_window(
            strategy_cls=strategy_cls,
            config_cls=config_cls,
            symbol=symbol,
            timeframe=timeframe,
            start=start_ts,
            end=end_ts,
            data_dir=resolved_data_dir,
            starting_balance=Decimal(str(starting_balance)),
            periods_per_year=resolved_periods_per_year,
            funding_assumptions=funding_assumptions,
        )
        funding_applied_all = funding_applied_all and window.funding_applied
        mark_to_market_applied_all = mark_to_market_applied_all and window.mark_to_market_applied
        results.append(SymbolResult(symbol, window.trades, window.equity))
        log.info(
            "symbol finished",
            symbol=symbol,
            trades=window.metrics.trade_metrics.trades,
            net_return=round(window.metrics.trade_metrics.net_return, 2),
        )

    combined_equity = combine_equity_curves(results, starting_balance)
    corr = correlation_matrix(results)
    hhi = concentration_hhi(results)
    drawdown = portfolio_drawdown(combined_equity)
    exposure = portfolio_exposure(results, start_ts, end_ts)

    avg_pairwise_correlation = None
    if not corr.empty and len(corr) > 1:
        upper_triangle = corr.to_numpy()[np.triu_indices(len(corr), k=1)]
        if len(upper_triangle) > 0:
            avg_pairwise_correlation = float(np.nanmean(upper_triangle))

    log.info(
        "portfolio summary",
        strategy=strategy,
        symbols=symbol_list,
        ending_equity=float(combined_equity.iloc[-1]) if not combined_equity.empty else None,
        portfolio_drawdown=drawdown,
        concentration_hhi=hhi,
        portfolio_exposure=exposure,
        avg_pairwise_correlation=avg_pairwise_correlation,
    )

    funding_meta = (
        {"applied": True, "rate_per_interval": str(funding_assumptions.rate_per_interval)}
        if funding_applied_all and funding_assumptions is not None
        else {"applied": False, "note": "--no-apply-funding was passed for this run"}
    )

    repo_root = Path(__file__).resolve().parents[1]
    store = ExperimentStore()
    record = ExperimentRecord(
        experiment_id=store.next_id(),
        git_commit=capture_git_commit(repo_root),
        dataset_version="multi-symbol",
        date_range=(start, end),
        symbols=tuple(symbol_list),
        timeframes=(timeframe,),
        strategy_version=f"{strategy}_portfolio",
        parameters={
            "starting_balance_per_symbol": starting_balance,
            "periods_per_year": resolved_periods_per_year,
            "periods_per_year_source": periods_per_year_source,
        },
        fees={"model": "maker_taker_from_instrument"},
        slippage={"prob_slippage": 0.2},
        funding_assumptions=funding_meta,
        metrics={
            "mark_to_market_applied": mark_to_market_applied_all,
            "portfolio_drawdown": drawdown,
            "concentration_hhi": hhi,
            "portfolio_exposure": exposure,
            "ending_equity": (
                float(combined_equity.iloc[-1]) if not combined_equity.empty else None
            ),
        },
    )
    store.save(record)
    save_report(record)
    log.info("portfolio backtest finished", experiment_id=record.experiment_id)


if __name__ == "__main__":
    app()
