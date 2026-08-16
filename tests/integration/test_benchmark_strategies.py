"""Each benchmark strategy must actually trade through the Phase 3 engine as designed.

These are integration tests against the real NautilusTrader engine (not
mocks) on deterministic synthetic price series, chosen so each strategy's
signal logic has a knowable, assertable outcome.

Note on the positions report: NautilusTrader's `side` column reflects the
position's *current* state (FLAT once closed), so it can't be used to check
which direction a closed round trip traded in - use `entry` (the opening
order's side, BUY/SELL) instead. `quantity` is the *remaining* size (0 once
closed) - use `peak_qty` (a string) for the size actually traded.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from src.strategies.buy_and_hold import BuyAndHold, BuyAndHoldConfig
from src.strategies.mean_reversion import MeanReversion, MeanReversionConfig
from src.strategies.random_entry import RandomEntry, RandomEntryConfig
from src.strategies.trend_following import TrendFollowing, TrendFollowingConfig
from tests.integration.helpers import run_strategy as _run


def test_buy_and_hold_enters_exactly_once_and_never_exits(tmp_path: Path) -> None:
    close = 100 + np.cumsum(np.random.default_rng(0).normal(0, 0.5, size=100))
    positions, _ = _run(tmp_path, close, BuyAndHold, BuyAndHoldConfig)

    assert len(positions) == 1
    assert positions["entry"].iloc[0] == "BUY"
    assert positions["side"].iloc[0] == "LONG"
    assert pd.isna(positions["avg_px_close"].iloc[0])  # still open at backtest end


def test_trend_following_is_always_long_on_a_pure_uptrend(tmp_path: Path) -> None:
    close = 100 + np.arange(300, dtype=float)  # strictly increasing, no noise
    positions, account = _run(tmp_path, close, TrendFollowing, TrendFollowingConfig)

    assert len(positions) > 0
    assert (positions["entry"] == "BUY").all()
    # Every round trip bought low and sold higher on a pure uptrend -> net profit.
    assert float(account["total"].iloc[-1]) > float(account["total"].iloc[0])


def test_trend_following_is_always_short_on_a_pure_downtrend(tmp_path: Path) -> None:
    close = 1000 - np.arange(300, dtype=float)
    positions, _ = _run(tmp_path, close, TrendFollowing, TrendFollowingConfig)

    assert len(positions) > 0
    assert (positions["entry"] == "SELL").all()


def test_mean_reversion_fades_a_sharp_extension_above_average(tmp_path: Path) -> None:
    # Flat for long enough to build the SMA lookback, then a sharp spike well
    # past the 2% threshold - mean reversion should fade it with a SELL.
    flat = np.full(30, 100.0)
    spike = np.full(20, 130.0)  # +30%, far past the default 2% threshold
    close = np.concatenate([flat, spike])
    positions, _ = _run(tmp_path, close, MeanReversion, MeanReversionConfig)

    assert len(positions) > 0
    assert positions["entry"].iloc[0] == "SELL"


def test_random_entry_is_reproducible_with_the_same_seed(tmp_path: Path) -> None:
    close = 100 + np.cumsum(np.random.default_rng(1).normal(0, 0.5, size=300))
    positions_a, _ = _run(tmp_path, close, RandomEntry, RandomEntryConfig, seed=123)
    positions_b, _ = _run(tmp_path, close, RandomEntry, RandomEntryConfig, seed=123)

    assert len(positions_a) == len(positions_b) > 0
    assert positions_a["entry"].tolist() == positions_b["entry"].tolist()


def test_random_entry_different_seeds_can_diverge(tmp_path: Path) -> None:
    close = 100 + np.cumsum(np.random.default_rng(2).normal(0, 0.5, size=300))
    positions_a, _ = _run(tmp_path, close, RandomEntry, RandomEntryConfig, seed=1)
    positions_b, _ = _run(tmp_path, close, RandomEntry, RandomEntryConfig, seed=2)

    assert positions_a["entry"].tolist() != positions_b["entry"].tolist()


def test_all_benchmarks_respect_the_configured_holding_period(tmp_path: Path) -> None:
    close = 100 + np.cumsum(np.random.default_rng(3).normal(0, 0.5, size=200))
    positions, _ = _run(
        tmp_path, close, RandomEntry, RandomEntryConfig, holding_period_bars=10, seed=5
    )
    ts_closed = pd.to_datetime(positions["ts_closed"], utc=True, errors="coerce")
    closed = positions[ts_closed.notna()]
    assert not closed.empty

    held_hours = (
        pd.to_datetime(closed["ts_closed"], utc=True) - closed["ts_opened"]
    ) / pd.Timedelta(hours=1)
    # Position is closed once holding_period_bars have elapsed since entry (1h bars).
    assert (held_hours <= 10 + 1).all()


@pytest.mark.parametrize(
    "strategy_cls,config_cls",
    [
        (TrendFollowing, TrendFollowingConfig),
        (MeanReversion, MeanReversionConfig),
        (RandomEntry, RandomEntryConfig),
    ],
)
def test_benchmarks_use_fixed_fraction_sizing_relative_to_equity(
    tmp_path: Path, strategy_cls, config_cls
) -> None:
    close = 100 + np.cumsum(np.random.default_rng(4).normal(0, 0.3, size=200))
    positions, account = _run(tmp_path, close, strategy_cls, config_cls)

    assert len(positions) > 0
    starting_balance = float(account["total"].iloc[0])
    first_peak_qty = float(positions["peak_qty"].iloc[0])
    first_entry_price = float(positions["avg_px_open"].iloc[0])
    first_entry_notional = first_peak_qty * first_entry_price
    # Default risk_fraction is 0.1 -> ~10% of starting equity, well under it entirely.
    assert 0 < first_entry_notional < starting_balance


class TestSessionFilter:
    def test_entries_only_happen_inside_the_session_window(self, tmp_path: Path) -> None:
        # Trending enough to produce many signals if unfiltered, so a session
        # filter with zero entries outside the window would be a real signal,
        # not just "this strategy happened not to trade then".
        close = 100 + np.cumsum(np.random.default_rng(7).normal(0, 0.3, size=400))
        positions, _ = _run(
            tmp_path,
            close,
            TrendFollowing,
            TrendFollowingConfig,
            session_start_hour=7,
            session_end_hour=16,
        )
        assert len(positions) > 0
        entry_hours = pd.to_datetime(positions["ts_opened"], utc=True).dt.hour
        assert entry_hours.between(7, 15).all()

    def test_positions_are_flattened_before_the_next_session_open(
        self, tmp_path: Path
    ) -> None:
        close = 100 + np.cumsum(np.random.default_rng(7).normal(0, 0.3, size=400))
        positions, _ = _run(
            tmp_path,
            close,
            TrendFollowing,
            TrendFollowingConfig,
            session_start_hour=7,
            session_end_hour=16,
            holding_period_bars=48,  # longer than the session itself (1h bars)
        )
        assert len(positions) > 0
        closed = positions[positions["ts_closed"].notna()]
        assert not closed.empty
        close_hours = pd.to_datetime(closed["ts_closed"], utc=True).dt.hour
        # Forced flat on the first bar outside [7, 16) - never held into the
        # next day's pre-session hours despite holding_period_bars=48.
        assert close_hours.between(7, 16).all()

    def test_session_config_rejects_only_one_bound_set(self) -> None:
        with pytest.raises(ValueError, match="must be set together"):
            TrendFollowingConfig(
                instrument_id=None,  # type: ignore[arg-type]
                bar_type=None,  # type: ignore[arg-type]
                session_start_hour=7,
            )

    def test_session_config_rejects_equal_bounds(self) -> None:
        with pytest.raises(ValueError, match="must differ"):
            TrendFollowingConfig(
                instrument_id=None,  # type: ignore[arg-type]
                bar_type=None,  # type: ignore[arg-type]
                session_start_hour=7,
                session_end_hour=7,
            )
