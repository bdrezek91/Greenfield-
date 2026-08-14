"""positions_report_to_trades must produce a trades frame whose net PnL matches
NautilusTrader's own realized_pnl - the strongest possible correctness check
for this adapter (no assumptions, cross-verified against the engine's ground truth).
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from src.analytics.metrics import trade_pnl
from src.backtesting.data_adapter import bar_type_for
from src.backtesting.engine import BacktestRunSpec, build_engine
from src.backtesting.reports import (
    _parse_money,
    account_report_to_equity,
    positions_report_to_trades,
)
from src.data.schema import COLUMNS
from src.data.storage import write_klines
from src.strategies.trend_following import TrendFollowing, TrendFollowingConfig


def _run_trend_following(tmp_path: Path) -> tuple[pd.DataFrame, pd.DataFrame]:
    close = 100 + np.cumsum(np.random.default_rng(9).normal(0.05, 0.5, size=300))
    ts = pd.date_range("2024-01-01", periods=len(close), freq="1h", tz="UTC")
    df = pd.DataFrame(
        {
            "timestamp": ts,
            "open": close,
            "high": close + 0.5,
            "low": close - 0.5,
            "close": close,
            "volume": 10.0,
            "turnover": 1000.0,
            "symbol": "BTCUSD",
            "timeframe": "1h",
        }
    )[list(COLUMNS)]
    write_klines(df, tmp_path)

    spec = BacktestRunSpec(
        symbols=["BTCUSD"], timeframe="1h", start=ts[0], end=ts[-1], data_dir=tmp_path
    )
    engine, instruments = build_engine(spec)
    instrument = instruments["BTCUSD"]
    bar_type = bar_type_for(instrument, "1h")
    engine.add_strategy(
        TrendFollowing(TrendFollowingConfig(instrument_id=instrument.id, bar_type=bar_type))
    )
    engine.run()
    positions = engine.trader.generate_positions_report()
    account = engine.trader.generate_account_report(next(iter(engine.list_venues())))
    engine.dispose()
    return positions, account


def test_trades_net_pnl_matches_engines_realized_pnl(tmp_path: Path) -> None:
    positions, _ = _run_trend_following(tmp_path)
    trades = positions_report_to_trades(positions)
    assert len(trades) > 0

    computed = trade_pnl(trades)
    engine_realized_pnl = [
        _parse_money(row.realized_pnl)
        for row in positions.itertuples()
        if pd.notna(row.ts_closed)
    ]

    assert len(engine_realized_pnl) == len(computed)
    for computed_pnl, expected_pnl in zip(
        computed["net_pnl"].tolist(), engine_realized_pnl, strict=True
    ):
        # NautilusTrader renders realized_pnl rounded to the account
        # currency's own precision (USD = 2 decimals, vs. USDT's 8 -
        # see docs/PROJECT_STATUS.md's exchange migration entry) - our own
        # trade_pnl() computes from full-precision entry/exit prices, so a
        # sub-cent gap between the two is the currency's rounding showing
        # up, not a real discrepancy. abs=0.01 covers a full cent of
        # rounding either way; tighter would be testing NautilusTrader's
        # display rounding, not our adapter's arithmetic.
        assert computed_pnl == pytest.approx(expected_pnl, abs=0.01)


def test_trades_excludes_still_open_positions(tmp_path: Path) -> None:
    positions, _ = _run_trend_following(tmp_path)
    trades = positions_report_to_trades(positions)
    still_open = positions[pd.to_datetime(positions["ts_closed"], errors="coerce").isna()]
    assert len(trades) == len(positions) - len(still_open)


def test_positions_report_to_trades_empty_input() -> None:
    trades = positions_report_to_trades(pd.DataFrame())
    assert trades.empty


def test_account_report_to_equity_is_a_float_series(tmp_path: Path) -> None:
    _, account = _run_trend_following(tmp_path)
    equity = account_report_to_equity(account)
    assert not equity.empty
    assert equity.dtype == float
    assert equity.index.tz is not None


def test_account_report_to_equity_empty_input() -> None:
    equity = account_report_to_equity(pd.DataFrame())
    assert equity.empty
