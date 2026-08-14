"""ML-filtered momentum strategy - Phase 13's "AI-enhanced strategy".

Per docs/ML.md's non-negotiable rule: an LLM/ML model never decides
BUY/SELL directly. Here the model only *filters* an already-deterministic
entry signal (src.strategies.signals.momentum_signal, the same rule
src.strategies.momentum.Momentum uses) - trade filtering / setup scoring is
one of the first-generation use cases named in
docs/PHASE_0_ARCHITECTURE_RESEARCH.md section 22. The decision procedure is
entirely deterministic and auditable:

    base_signal = momentum_signal(...)                     # rule-based
    if base_signal is None: stay flat
    proba = model.predict_proba(features_at_this_bar)       # frozen artifact
    if proba >= probability_threshold: take base_signal
    else: stay flat

No LLM is involved anywhere in this path; "AI-enhanced" here means a
frozen, versioned scikit-learn artifact (src.ml.model_io), not a live model
call, let alone a prompt.

Two safety properties enforced at construction/runtime, not just by
convention:
  1. The loaded model's `feature_columns` must exactly match
     `src.features.pipeline.FEATURE_COLUMNS` - a schema mismatch (e.g. a
     model trained against an older feature pipeline) fails loudly at
     `on_start()`, never silently feeds misaligned columns to the model.
  2. Per docs/RESEARCH_METHODOLOGY.md: never evaluate a strategy on data it
     was optimized on. Bars at or before the model's recorded
     `metadata.train_end` are never traded on, even if the backtest window
     given to this strategy happens to overlap the training window - this
     is an in-strategy guard, not just a documentation note.
"""

from __future__ import annotations

from collections import deque
from pathlib import Path

import pandas as pd
from nautilus_trader.model.data import Bar
from nautilus_trader.model.enums import OrderSide

from src.features.pipeline import FEATURE_COLUMNS, build_feature_matrix
from src.ml.model_io import load_model
from src.strategies.base import BenchmarkStrategyConfig, HoldForBarsStrategy
from src.strategies.signals import momentum_signal


class MLFilteredConfig(BenchmarkStrategyConfig, frozen=True):  # type: ignore[call-arg]
    # No default despite following BenchmarkStrategyConfig's defaulted fields
    # would violate msgspec.Struct's required-before-optional field order, so
    # this defaults to "" and __init__ rejects that immediately - a strategy
    # silently picking "some" model is worse than a loud constructor error.
    model_path: str = ""
    probability_threshold: float = 0.55
    momentum_lookback_bars: int = 10
    momentum_threshold: float = 0.01
    feature_warmup_bars: int = 150


class MLFiltered(HoldForBarsStrategy):
    def __init__(self, config: MLFilteredConfig) -> None:
        super().__init__(config)
        if not config.model_path:
            raise ValueError("MLFilteredConfig.model_path is required")
        self._model, self._metadata = load_model(Path(config.model_path))
        if tuple(self._metadata.feature_columns) != FEATURE_COLUMNS:
            raise ValueError(
                "model feature schema does not match the current feature pipeline: "
                f"model has {self._metadata.feature_columns}, "
                f"pipeline has {FEATURE_COLUMNS}"
            )
        self._train_end = pd.Timestamp(self._metadata.train_end)
        self._closes: deque[float] = deque(maxlen=config.momentum_lookback_bars + 1)
        self._bar_buffer: deque[dict[str, float | pd.Timestamp]] = deque(
            maxlen=config.feature_warmup_bars
        )
        self._warned_in_sample = False

    def signal(self, bar: Bar) -> OrderSide | None:
        self._closes.append(float(bar.close))
        bar_ts = pd.Timestamp(bar.ts_event, unit="ns", tz="UTC")
        self._bar_buffer.append(
            {
                "timestamp": bar_ts,
                "open": float(bar.open),
                "high": float(bar.high),
                "low": float(bar.low),
                "close": float(bar.close),
                "volume": float(bar.volume),
            }
        )

        base_signal = momentum_signal(
            self._closes, self.config.momentum_lookback_bars, self.config.momentum_threshold
        )
        if base_signal is None:
            return None

        if bar_ts <= self._train_end:
            if not self._warned_in_sample:
                self.log.warning(
                    "MLFiltered: bar timestamp is within the model's training window "
                    f"({bar_ts} <= {self._train_end}) - refusing to trade in-sample."
                )
                self._warned_in_sample = True
            return None

        if len(self._bar_buffer) < self.config.feature_warmup_bars:
            return None  # not enough history for a reliable feature vector yet

        df = pd.DataFrame(list(self._bar_buffer))
        features = build_feature_matrix(df)
        last_row = features.iloc[[-1]][list(FEATURE_COLUMNS)]
        if last_row.isna().any(axis=None):
            return None  # feature warmup not yet satisfied for this config

        proba = float(self._model.predict_proba(last_row)[0])  # type: ignore[attr-defined]
        if proba >= self.config.probability_threshold:
            return base_signal
        return None
