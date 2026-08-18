"""positions_report_to_trades: mark-to-market for still-open positions and
funding-cost wiring (docs/AUTONOMOUS_RESEARCH_AUDIT.md findings M2, M3).

Uses a synthetic DataFrame with the same columns NautilusTrader's
`generate_positions_report()` produces, so this can run without the engine
(the engine-level, end-to-end version of these checks lives in
tests/integration/test_reports_adapter.py).
"""

from __future__ import annotations

from decimal import Decimal

import pandas as pd
import pytest

from src.analytics.metrics import compute_equity_metrics
from src.backtesting.funding import FundingAssumptions
from src.backtesting.reports import mark_to_market_equity, positions_report_to_trades

_OPENED = pd.Timestamp("2024-01-01T00:00:00", tz="UTC")
_CLOSED = pd.Timestamp("2024-01-01T05:00:00", tz="UTC")
_PERIOD_END = pd.Timestamp("2024-01-01T10:00:00", tz="UTC")


def _positions(*, still_open: bool, side: str = "BUY") -> pd.DataFrame:
    return pd.DataFrame(
        {
            "entry": [side],
            "ts_opened": [_OPENED],
            "ts_closed": [pd.NaT if still_open else _CLOSED],
            "avg_px_open": [100.0],
            "avg_px_close": [None if still_open else 110.0],
            "peak_qty": [2.0],
            "commissions": [[] if still_open else ["1.0 USDT"]],
        }
    )


def test_open_position_excluded_by_default_matches_old_behavior() -> None:
    trades = positions_report_to_trades(_positions(still_open=True))
    assert trades.empty


def test_open_position_marked_to_market_when_period_end_and_price_given() -> None:
    trades = positions_report_to_trades(
        _positions(still_open=True), period_end=_PERIOD_END, mark_price=120.0
    )
    assert len(trades) == 1
    row = trades.iloc[0]
    assert row["exit_time"] == _PERIOD_END
    assert row["exit_price"] == 120.0
    assert row["quantity"] == 2.0  # BUY -> long, positive
    assert bool(row["is_mark_to_market"]) is True
    assert row["fees"] == 0.0  # no closing commission was actually charged


def test_mark_to_market_unrealized_pnl_reflects_price_move() -> None:
    trades = positions_report_to_trades(
        _positions(still_open=True), period_end=_PERIOD_END, mark_price=120.0
    )
    row = trades.iloc[0]
    gross_pnl = row["quantity"] * (row["exit_price"] - row["entry_price"])
    assert gross_pnl == pytest.approx(2.0 * (120.0 - 100.0))


def test_short_open_position_marked_to_market_direction() -> None:
    trades = positions_report_to_trades(
        _positions(still_open=True, side="SELL"), period_end=_PERIOD_END, mark_price=90.0
    )
    row = trades.iloc[0]
    assert row["quantity"] == -2.0
    gross_pnl = row["quantity"] * (row["exit_price"] - row["entry_price"])
    assert gross_pnl == pytest.approx(-2.0 * (90.0 - 100.0))  # short profits when price falls


def test_closed_and_open_positions_both_included_when_marking_to_market() -> None:
    positions = pd.concat(
        [_positions(still_open=False), _positions(still_open=True)], ignore_index=True
    )
    trades = positions_report_to_trades(positions, period_end=_PERIOD_END, mark_price=120.0)
    assert len(trades) == 2
    assert trades["is_mark_to_market"].tolist() == [False, True]


def test_missing_mark_price_does_not_include_open_position() -> None:
    trades = positions_report_to_trades(_positions(still_open=True), period_end=_PERIOD_END)
    assert trades.empty


def test_no_funding_assumptions_leaves_funding_cost_zero() -> None:
    trades = positions_report_to_trades(_positions(still_open=False))
    assert (trades["funding_cost"] == 0.0).all()


def test_funding_assumptions_charge_closed_trade() -> None:
    assumptions = FundingAssumptions(rate_per_interval=Decimal("0.0001"))
    trades = positions_report_to_trades(
        _positions(still_open=False), funding_assumptions=assumptions
    )
    # Held 2024-01-01T00:00 -> 05:00, crosses only the 00:00 settlement
    # (start is inclusive at the open, 00:00 falls within [start, end)).
    expected = 1 * (2.0 * 100.0) * 0.0001
    assert trades.iloc[0]["funding_cost"] == pytest.approx(expected)


def test_funding_charged_through_period_end_for_still_open_position() -> None:
    assumptions = FundingAssumptions(rate_per_interval=Decimal("0.0001"))
    trades = positions_report_to_trades(
        _positions(still_open=True),
        period_end=_PERIOD_END,
        mark_price=120.0,
        funding_assumptions=assumptions,
    )
    # Held 00:00 -> 10:00, crosses the 00:00 and 08:00 settlements.
    expected = 2 * (2.0 * 100.0) * 0.0001
    assert trades.iloc[0]["funding_cost"] == pytest.approx(expected)


def test_empty_positions_returns_empty_with_all_columns() -> None:
    trades = positions_report_to_trades(pd.DataFrame())
    assert trades.empty
    assert "funding_cost" in trades.columns
    assert "is_mark_to_market" in trades.columns


def test_regular_mtm_equity_captures_intratrade_twenty_percent_drawdown() -> None:
    times = pd.date_range("2024-01-01 01:00", periods=3, freq="1h", tz="UTC")
    closes = pd.Series([100.0, 80.0, 100.0], index=times)
    trades = pd.DataFrame(
        {
            "entry_time": [times[0]],
            "exit_time": [times[2]],
            "quantity": [10.0],
            "entry_price": [100.0],
            "exit_price": [100.0],
            "fees": [0.0],
            "funding_cost": [0.0],
        }
    )
    equity = mark_to_market_equity(trades, closes, starting_balance=1000.0)
    metrics = compute_equity_metrics(equity, periods_per_year=8760)
    assert equity.iloc[-1] == pytest.approx(1000.0)
    assert metrics.max_drawdown == pytest.approx(-0.20)


def test_open_position_keeps_real_entry_fee_without_fake_exit_fee() -> None:
    positions = _positions(still_open=True)
    positions.at[0, "commissions"] = ["1.5 USDT"]
    trades = positions_report_to_trades(
        positions, period_end=_PERIOD_END, mark_price=100.0
    )
    assert trades.iloc[0]["fees"] == pytest.approx(1.5)
