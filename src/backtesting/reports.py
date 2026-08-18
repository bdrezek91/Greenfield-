"""Adapt NautilusTrader's report DataFrames into the generic contracts
src.analytics.metrics expects (see that module's docstring). This is the
only place besides engine.py/data_adapter.py that touches NautilusTrader's
report shapes - the analytics layer stays engine-independent.
"""

from __future__ import annotations

import pandas as pd

from src.backtesting.funding import FundingAssumptions, funding_cashflows

TRADE_COLUMNS = (
    "entry_time",
    "exit_time",
    "quantity",
    "entry_price",
    "exit_price",
    "fees",
    "funding_cost",
    "funding_cashflows",
    "is_mark_to_market",
)


def _parse_money(value: str) -> float:
    """NautilusTrader renders Money as e.g. '12.09949327 USDT' - take the numeric part."""
    return float(value.split(" ")[0])


def positions_report_to_trades(
    positions: pd.DataFrame,
    *,
    period_end: pd.Timestamp | None = None,
    mark_price: float | None = None,
    funding_assumptions: FundingAssumptions | None = None,
) -> pd.DataFrame:
    """Adapt NautilusTrader's positions report into the generic trades contract.

    Closed positions become ordinary trade rows. A position still open at
    `period_end` is NOT a completed round trip, but excluding it entirely
    (the historical behavior here) makes every metric derived from `trades`
    - most importantly `net_return` - blind to that position's unrealized
    PnL. For Buy & Hold, which never closes its position, that made the
    reported net_return always 0 regardless of the real price move (see
    docs/AUTONOMOUS_RESEARCH_AUDIT.md, finding M3).

    Passing both `period_end` and `mark_price` marks every still-open
    position to `mark_price` as of `period_end` and includes it as a trade
    row with `is_mark_to_market=True` (no closing fee is charged - the
    position was never actually closed, so pretending a closing commission
    was paid would be fabricating a cost that didn't happen). Omitting
    either argument keeps the exact old behavior (closed positions only) -
    existing callers are unaffected.

    `funding_assumptions`, if given, computes each trade's `funding_cost`
    via `src.backtesting.funding.estimate_funding_cost` over its actual
    holding period (a still-open position is charged through `period_end`).
    Omitting it leaves `funding_cost` at 0.0, as before - a backtest run
    without funding assumptions is not silently charged a value nobody
    asked for.
    """
    if positions.empty:
        return pd.DataFrame(columns=TRADE_COLUMNS)

    ts_closed = pd.to_datetime(positions["ts_closed"], utc=True, errors="coerce")
    closed = positions[ts_closed.notna()].copy()
    closed["ts_closed"] = pd.to_datetime(closed["ts_closed"], utc=True)

    open_positions = positions[ts_closed.isna()].copy()
    include_open = period_end is not None and mark_price is not None and not open_positions.empty

    if closed.empty and not include_open:
        return pd.DataFrame(columns=TRADE_COLUMNS)

    frames = []
    if not closed.empty:
        direction = closed["entry"].map({"BUY": 1.0, "SELL": -1.0})
        fees = closed["commissions"].apply(
            lambda entries: sum(_parse_money(entry) for entry in entries) if entries else 0.0
        )
        closed_frame = pd.DataFrame(
            {
                "entry_time": closed["ts_opened"],
                "exit_time": closed["ts_closed"],
                "quantity": closed["peak_qty"].astype(float) * direction,
                "entry_price": closed["avg_px_open"].astype(float),
                "exit_price": closed["avg_px_close"].astype(float),
                "fees": fees,
                "is_mark_to_market": False,
            }
        )
        frames.append(closed_frame)

    if include_open:
        assert mark_price is not None  # noqa: S101 - narrows for mypy, guaranteed by include_open
        direction = open_positions["entry"].map({"BUY": 1.0, "SELL": -1.0})
        fees = open_positions["commissions"].apply(
            lambda entries: sum(_parse_money(entry) for entry in entries) if entries else 0.0
        )
        open_frame = pd.DataFrame(
            {
                "entry_time": open_positions["ts_opened"],
                "exit_time": period_end,
                "quantity": open_positions["peak_qty"].astype(float) * direction,
                "entry_price": open_positions["avg_px_open"].astype(float),
                "exit_price": float(mark_price),
                # Entry/partial-fill commissions were genuinely paid even
                # though no fictional exit commission may be charged.
                "fees": fees,
                "is_mark_to_market": True,
            }
        )
        frames.append(open_frame)

    trades = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame(columns=TRADE_COLUMNS)

    if funding_assumptions is not None and not trades.empty:
        funding_input = pd.DataFrame(
            {
                "ts_opened": trades["entry_time"],
                "ts_closed": trades["exit_time"],
                "avg_px_open": trades["entry_price"],
                "quantity": trades["quantity"],
            }
        )
        schedules = [
            funding_cashflows(funding_input.iloc[[i]], funding_assumptions)
            for i in range(len(funding_input))
        ]
        trades["funding_cashflows"] = schedules
        trades["funding_cost"] = [
            sum(cost for _timestamp, cost in schedule) for schedule in schedules
        ]
    else:
        trades["funding_cost"] = 0.0
        trades["funding_cashflows"] = [[] for _ in range(len(trades))]

    return trades[list(TRADE_COLUMNS)].reset_index(drop=True)


def account_report_to_equity(account: pd.DataFrame) -> pd.Series:
    """The account report's `total` balance over time, indexed by timestamp -
    an event-driven (irregularly sampled) equity curve, not fixed-interval
    bars. Fine for cumulative metrics (net return, CAGR, drawdown); Sharpe/
    Sortino's annualization is an approximation under irregular sampling.
    """
    if account.empty:
        return pd.Series(dtype=float)
    return account["total"].astype(float)


def mark_to_market_equity(
    trades: pd.DataFrame,
    closes: pd.Series,
    *,
    starting_balance: float,
) -> pd.Series:
    """Build regular per-bar equity from realized and unrealized PnL.

    ``closes`` must be indexed by bar close/information-availability time.
    Fees (including spread) are deducted at entry (conservative when a
    closed position's report only exposes aggregate commissions). Historical
    funding is deducted on its actual settlement bar, so Sharpe, DSR and
    drawdown consume the same net-of-cost per-bar curve as total return.
    """
    if closes.empty:
        return pd.Series(dtype=float)
    prices = closes.astype(float).sort_index()
    equity = pd.Series(float(starting_balance), index=prices.index, dtype=float)
    if trades.empty:
        return equity

    for row in trades.itertuples():
        entry = pd.Timestamp(row.entry_time)
        exit_time = pd.Timestamp(row.exit_time)
        qty = float(row.quantity)
        entry_price = float(row.entry_price)
        exit_price = float(row.exit_price)
        fees = float(getattr(row, "fees", 0.0) or 0.0)
        funding = float(getattr(row, "funding_cost", 0.0) or 0.0)
        cashflows = list(getattr(row, "funding_cashflows", []) or [])

        active = (prices.index >= entry) & (prices.index < exit_time)
        after = prices.index >= exit_time
        equity.loc[active] += qty * (prices.loc[active] - entry_price) - fees
        equity.loc[after] += qty * (exit_price - entry_price) - fees
        if cashflows:
            for timestamp, cost in cashflows:
                equity.loc[prices.index >= pd.Timestamp(timestamp)] -= float(cost)
        else:
            equity.loc[after] -= funding
    return equity
