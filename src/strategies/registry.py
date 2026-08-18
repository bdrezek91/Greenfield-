"""Name -> (Strategy, StrategyConfig) lookups used by scripts/run_backtest.py and
scripts/compare_strategies.py to select strategies from the command line.

BENCHMARK_STRATEGIES are the four mandatory sanity checks from
docs/RESEARCH_METHODOLOGY.md (section 11 of the project brief) - every
strategy family must be compared against and beat these. STRATEGY_FAMILIES
are the first real families under research (Phase 6) - deliberately a
handful, not the full list from docs/PHASE_0_ARCHITECTURE_RESEARCH.md, per
section 12's "build the comparison framework first, not dozens of variants."

AI_ENHANCED_STRATEGIES (Phase 13) is deliberately kept OUT of
ALL_STRATEGIES: MLFilteredConfig.model_path has no default (a strategy
that silently picked "some" model artifact would be a footgun), so the
generic scripts that construct `config_cls(instrument_id=..., bar_type=...)`
with no other kwargs (compare_strategies.py, monte_carlo.py, etc.) would
fail confusingly on it. scripts/run_ml_strategy.py is the dedicated
entry point that supplies --model-path explicitly.
"""

from __future__ import annotations

from src.strategies.breakout import Breakout, BreakoutConfig
from src.strategies.buy_and_hold import BuyAndHold, BuyAndHoldConfig
from src.strategies.cross_asset_momentum import CrossAssetMomentum, CrossAssetMomentumConfig
from src.strategies.cross_sectional_momentum import (
    CrossSectionalMomentum,
    CrossSectionalMomentumConfig,
)
from src.strategies.funding_carry import FundingCarry, FundingCarryConfig
from src.strategies.funding_contrarian import FundingContrarian, FundingContrarianConfig
from src.strategies.liquidity_sweep_confluence import (
    LiquiditySweepConfluence,
    LiquiditySweepConfluenceConfig,
)
from src.strategies.mean_reversion import MeanReversion, MeanReversionConfig
from src.strategies.ml_filtered import MLFiltered, MLFilteredConfig
from src.strategies.momentum import Momentum, MomentumConfig
from src.strategies.random_entry import RandomEntry, RandomEntryConfig
from src.strategies.trend_following import TrendFollowing, TrendFollowingConfig
from src.strategies.volatility_expansion import VolatilityExpansion, VolatilityExpansionConfig

BENCHMARK_STRATEGIES = {
    "buy_and_hold": (BuyAndHold, BuyAndHoldConfig),
    "random_entry": (RandomEntry, RandomEntryConfig),
    "trend_following": (TrendFollowing, TrendFollowingConfig),
    "mean_reversion": (MeanReversion, MeanReversionConfig),
}

STRATEGY_FAMILIES = {
    "momentum": (Momentum, MomentumConfig),
    "breakout": (Breakout, BreakoutConfig),
    "volatility_expansion": (VolatilityExpansion, VolatilityExpansionConfig),
}

AI_ENHANCED_STRATEGIES = {
    "ml_filtered": (MLFiltered, MLFilteredConfig),
}

# Also deliberately kept OUT of ALL_STRATEGIES, same reasoning as
# AI_ENHANCED_STRATEGIES above: CrossAssetMomentumConfig's
# reference_instrument_id/reference_bar_type have no safe default (there is
# no such thing as "some" reference symbol), so the generic scripts that
# construct `config_cls(instrument_id=..., bar_type=...)` with no other
# kwargs would fail confusingly on it. src/research/queue.py and
# src/research/orchestrator.py supply the reference symbol explicitly for
# every hypothesis in the cross_asset_regime family.
CROSS_ASSET_STRATEGIES = {
    "cross_asset_momentum": (CrossAssetMomentum, CrossAssetMomentumConfig),
    "cross_sectional_momentum": (CrossSectionalMomentum, CrossSectionalMomentumConfig),
}

# Also kept OUT of ALL_STRATEGIES: FundingContrarianConfig.data_dir has no
# safe default (there is no such thing as "some" data directory), same
# reasoning as CROSS_ASSET_STRATEGIES above. src/research/queue.py and
# src/research/orchestrator.py supply data_dir explicitly for every
# hypothesis in the funding_oi family.
FUNDING_OI_STRATEGIES = {
    "funding_contrarian": (FundingContrarian, FundingContrarianConfig),
    "funding_carry": (FundingCarry, FundingCarryConfig),
}

# Also kept OUT of ALL_STRATEGIES, same reasoning as FUNDING_OI_STRATEGIES:
# LiquiditySweepConfluenceConfig.data_dir has no safe default.
PRICE_ACTION_STRATEGIES = {
    "liquidity_sweep_confluence": (LiquiditySweepConfluence, LiquiditySweepConfluenceConfig),
}

ALL_STRATEGIES = {**BENCHMARK_STRATEGIES, **STRATEGY_FAMILIES}

# Superset used only by src/research/orchestrator.py, which knows how to
# supply every strategy's non-default-safe config fields (reference symbol,
# model path, data directory) explicitly per hypothesis - never used by the
# generic CLI scripts (compare_strategies.py, monte_carlo.py, etc.), which
# stay on ALL_STRATEGIES so an operator can never accidentally select a
# strategy that needs configuration those scripts don't know how to provide.
RESEARCH_STRATEGIES = {
    **ALL_STRATEGIES,
    **CROSS_ASSET_STRATEGIES,
    **FUNDING_OI_STRATEGIES,
    **PRICE_ACTION_STRATEGIES,
}
