"""Portfolio aggregation must combine per-symbol results with hand-verifiable math."""

from __future__ import annotations

import math

import pandas as pd
import pytest

from src.portfolio.aggregation import (
    SymbolResult,
    combine_equity_curves,
    concentration_hhi,
    correlation_matrix,
    portfolio_drawdown,
    portfolio_exposure,
)


def _empty_trades() -> pd.DataFrame:
    return pd.DataFrame(columns=["entry_time", "exit_time", "quantity", "entry_price", "fees"])


def test_combine_equity_curves_sums_pnl_on_shared_starting_balance() -> None:
    idx = pd.date_range("2024-01-01", periods=3, freq="D", tz="UTC")
    btc = SymbolResult(
        "BTCUSD", _empty_trades(), pd.Series([1000.0, 1100.0, 1050.0], index=idx)
    )
    eth = SymbolResult(
        "ETHUSD", _empty_trades(), pd.Series([1000.0, 950.0, 1000.0], index=idx)
    )
    combined = combine_equity_curves([btc, eth], starting_balance=1000.0)

    # PnL BTC: [0, 100, 50]; PnL ETH: [0, -50, 0]; combined = 1000 + sum.
    assert combined.tolist() == pytest.approx([1000.0, 1050.0, 1050.0])


def test_combine_equity_curves_aligns_mismatched_timelines() -> None:
    idx1 = pd.date_range("2024-01-01", periods=2, freq="D", tz="UTC")
    idx2 = pd.date_range("2024-01-02", periods=2, freq="D", tz="UTC")
    a = SymbolResult("A", _empty_trades(), pd.Series([1000.0, 1100.0], index=idx1))
    b = SymbolResult("B", _empty_trades(), pd.Series([1000.0, 1200.0], index=idx2))

    combined = combine_equity_curves([a, b], starting_balance=1000.0)
    # Union index: Jan1, Jan2, Jan3.
    # A's pnl: Jan1=0, Jan2=100 (last known); B's pnl ffilled before its own
    # start is 0 (fillna(0.0)), Jan2=0, Jan3=200.
    assert len(combined) == 3
    assert combined.iloc[0] == pytest.approx(1000.0)
    assert combined.iloc[-1] == pytest.approx(1000.0 + 100.0 + 200.0)


def test_combine_equity_curves_empty_input() -> None:
    assert combine_equity_curves([], starting_balance=1000.0).empty


def test_combine_equity_curves_handles_duplicate_timestamps() -> None:
    # NautilusTrader's account report can have multiple rows at the same
    # timestamp (e.g. order submit + fill); reindex() requires a unique
    # index, so duplicates must be collapsed (to the last value) first.
    idx = pd.to_datetime(
        ["2024-01-01T00:00", "2024-01-01T01:00", "2024-01-01T01:00", "2024-01-01T02:00"],
        utc=True,
    )
    a = SymbolResult("A", _empty_trades(), pd.Series([1000.0, 1000.0, 1050.0, 1050.0], index=idx))
    combined = combine_equity_curves([a], starting_balance=1000.0)
    assert len(combined) == 3  # duplicate timestamp collapsed
    assert combined.iloc[-1] == pytest.approx(1050.0)


def test_combine_equity_curves_skips_empty_symbol_equity() -> None:
    idx = pd.date_range("2024-01-01", periods=2, freq="D", tz="UTC")
    a = SymbolResult("A", _empty_trades(), pd.Series([1000.0, 1050.0], index=idx))
    b = SymbolResult("B", _empty_trades(), pd.Series(dtype=float))
    combined = combine_equity_curves([a, b], starting_balance=1000.0)
    assert combined.tolist() == pytest.approx([1000.0, 1050.0])


def test_correlation_matrix_perfectly_correlated() -> None:
    idx = pd.date_range("2024-01-01", periods=5, freq="D", tz="UTC")
    a = SymbolResult("A", _empty_trades(), pd.Series([100, 110, 121, 133.1, 146.41], index=idx))
    b = SymbolResult("B", _empty_trades(), pd.Series([200, 220, 242, 266.2, 292.82], index=idx))
    corr = correlation_matrix([a, b])
    assert corr.loc["A", "B"] == pytest.approx(1.0, abs=1e-6)


def test_correlation_matrix_needs_at_least_two_symbols() -> None:
    idx = pd.date_range("2024-01-01", periods=3, freq="D", tz="UTC")
    a = SymbolResult("A", _empty_trades(), pd.Series([100, 110, 121], index=idx))
    assert correlation_matrix([a]).empty


def test_concentration_hhi_even_split() -> None:
    trades_a = pd.DataFrame({"quantity": [1.0], "entry_price": [100.0]})
    trades_b = pd.DataFrame({"quantity": [1.0], "entry_price": [100.0]})
    a = SymbolResult("A", trades_a, pd.Series(dtype=float))
    b = SymbolResult("B", trades_b, pd.Series(dtype=float))
    hhi = concentration_hhi([a, b])
    assert hhi == pytest.approx(0.5)  # two equal shares -> 0.5^2 + 0.5^2


def test_concentration_hhi_all_in_one_symbol() -> None:
    trades_a = pd.DataFrame({"quantity": [1.0], "entry_price": [100.0]})
    a = SymbolResult("A", trades_a, pd.Series(dtype=float))
    b = SymbolResult("B", _empty_trades(), pd.Series(dtype=float))
    assert concentration_hhi([a, b]) == pytest.approx(1.0)


def test_concentration_hhi_no_trades_is_nan() -> None:
    a = SymbolResult("A", _empty_trades(), pd.Series(dtype=float))
    assert math.isnan(concentration_hhi([a]))


def test_portfolio_drawdown_known_value() -> None:
    idx = pd.date_range("2024-01-01", periods=4, freq="D", tz="UTC")
    equity = pd.Series([1000.0, 1200.0, 900.0, 1100.0], index=idx)
    assert portfolio_drawdown(equity) == pytest.approx((900.0 - 1200.0) / 1200.0)


def test_portfolio_drawdown_empty_is_zero() -> None:
    assert portfolio_drawdown(pd.Series(dtype=float)) == 0.0


def test_portfolio_exposure_union_across_symbols() -> None:
    start = pd.Timestamp("2024-01-01T00:00", tz="UTC")
    end = pd.Timestamp("2024-01-02T00:00", tz="UTC")
    trades_a = pd.DataFrame(
        {
            "entry_time": pd.to_datetime(["2024-01-01T00:00"], utc=True),
            "exit_time": pd.to_datetime(["2024-01-01T06:00"], utc=True),
        }
    )
    trades_b = pd.DataFrame(
        {
            "entry_time": pd.to_datetime(["2024-01-01T12:00"], utc=True),
            "exit_time": pd.to_datetime(["2024-01-01T18:00"], utc=True),
        }
    )
    a = SymbolResult("A", trades_a, pd.Series(dtype=float))
    b = SymbolResult("B", trades_b, pd.Series(dtype=float))
    # Two disjoint 6h windows out of 24h -> 12h / 24h = 0.5.
    assert portfolio_exposure([a, b], start, end) == pytest.approx(0.5)


def test_portfolio_exposure_no_trades_is_zero() -> None:
    start = pd.Timestamp("2024-01-01", tz="UTC")
    end = pd.Timestamp("2024-01-02", tz="UTC")
    a = SymbolResult("A", _empty_trades(), pd.Series(dtype=float))
    assert portfolio_exposure([a], start, end) == 0.0
