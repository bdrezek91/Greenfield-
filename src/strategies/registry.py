"""Name -> (Strategy, StrategyConfig) lookup for the benchmark strategies, used by
scripts/run_backtest.py so a strategy can be selected from the command line.
"""

from __future__ import annotations

from src.strategies.buy_and_hold import BuyAndHold, BuyAndHoldConfig
from src.strategies.mean_reversion import MeanReversion, MeanReversionConfig
from src.strategies.random_entry import RandomEntry, RandomEntryConfig
from src.strategies.trend_following import TrendFollowing, TrendFollowingConfig

BENCHMARK_STRATEGIES = {
    "buy_and_hold": (BuyAndHold, BuyAndHoldConfig),
    "random_entry": (RandomEntry, RandomEntryConfig),
    "trend_following": (TrendFollowing, TrendFollowingConfig),
    "mean_reversion": (MeanReversion, MeanReversionConfig),
}
