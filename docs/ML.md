# Machine Learning / AI

## Principles

- AI is a separate layer (`src/ml`), not assumed to improve results. If it
  doesn't beat a simple baseline out-of-sample, it gets rejected — same as
  any other experiment (see `docs/RESEARCH_METHODOLOGY.md`).
- No next-candle price prediction. First-generation use cases: setup
  scoring, regime classification, expected return/R, volatility prediction,
  trade filtering, position sizing.
- No LLM-as-decision-maker. LLMs (including Claude) are used for research,
  reports, experiment analysis, hypothesis generation, and debugging — never
  to decide BUY/SELL through a prompt. Trading decisions must be
  deterministic and auditable code.

## Baseline-first

Before anything expensive: Logistic Regression, Random Forest, Extra Trees.
Only if these are beaten out-of-sample do LightGBM/XGBoost/CatBoost get
considered, and only after those, if there is a specific, justified
hypothesis, deep learning.

## Splitting

Never a random `train_test_split`. Time-series split, purged split, or
walk-forward, with purging/embargo where overlapping labels (e.g. "R after N
candles") could otherwise leak information across the split boundary.

## Calibration & explainability

- Any model that outputs `P(win)` is checked for calibration (Brier Score,
  calibration curve).
- Every model reports feature importance, permutation importance, and SHAP
  where applicable. No black-box model without diagnostics.

## Feature inputs

ML models consume only the output of `src/features` (point-in-time, no
lookahead) — never raw data with access to information beyond the prediction
point.

## Implementation (Phase 11 — research framework)

No model is trained in this phase; this is the framework Phase 12's
baseline comparison will run inside.

- `src/features/` (price.py, volatility.py, volume.py, structure.py,
  pipeline.py) — the section 23 feature families. `volatility.py` reuses
  ATR/realized volatility from `src.regimes.indicators` (Phase 8) rather
  than duplicating them. `pipeline.py:build_feature_matrix()` is the single
  assembly entry point; every feature is proven lookahead-free in
  `tests/lookahead/test_feature_no_lookahead.py`.
- `src/ml/labels.py` — `forward_return_label`, `direction_label`,
  `expected_r_label`. Labels legitimately look forward (that's what makes
  them a target, not a feature) - each also returns a `label_end_time`,
  which `splits.py` needs for purging.
- `src/ml/splits.py` — `time_series_split` (plain chronological) and
  `purged_kfold_split` (removes training rows whose label window overlaps
  a test fold, plus an embargo buffer after it) — never a random
  `train_test_split`, per section 25.
- `src/ml/calibration.py` — `brier_score`, `calibration_curve`, implemented
  from scratch (no ML dependency needed yet).
- `src/ml/explainability.py` — model-agnostic `permutation_importance`
  (works against any `.predict()`-shaped model). Native feature importance
  and SHAP require an actual trained model and land with it in Phase 12.
- `src/ml/baseline.py` — the `Model` protocol (`fit`/`predict`/
  `predict_proba`) Phase 12's implementations are expected to satisfy.
- `scripts/prepare_ml_dataset.py` — demonstrates the framework end to end
  on real data: load klines → build features → build a label → purged
  split, with no model trained.

No `scikit-learn`/`lightgbm` dependency was installed in Phase 11 -
consistent with this project's practice of not installing a dependency
before code uses it (see e.g. `vectorbt`'s deferral through Phases 3-6).
Phase 12 (below) activates the `ml` extras group.

## Implementation (Phase 12 — baseline models)

The `ml` extras group (`scikit-learn`, `lightgbm`) is now active. Only
`scikit-learn` is used so far — `lightgbm` stays installed but unused until
a baseline is actually beaten (see Baseline-first, above).

- `src/ml/models/naive.py` — `NaivePriorBaseline`: predicts the training
  set's class prior for every row, ignoring features entirely. This is the
  bar every real model must clear out-of-sample before it earns further
  consideration, per section 24.
- `src/ml/models/sklearn_models.py` — `LogisticRegressionModel`,
  `RandomForestModel`, `ExtraTreesModel`, all satisfying `src.ml.baseline.Model`
  and all using `class_weight="balanced"` (trading labels are rarely
  50/50). The two tree models also expose `.feature_importances()` (native
  impurity-based importance), reported alongside — never instead of —
  permutation importance.
- `src/ml/evaluation.py` — `run_comparison()` trains a fresh model per
  fold (no state carried across folds) and reports accuracy/ROC-AUC/Brier;
  `summarize_comparison()` ranks by mean Brier; `beats_baseline_every_fold()`
  requires a model to have strictly lower Brier than the naive baseline on
  *every* fold, not just on average — the same per-fold robustness standard
  used elsewhere in this project (see `docs/RESEARCH_METHODOLOGY.md`).
- `scripts/train_baseline_models.py` — end-to-end CLI: klines → features →
  binary direction label (`forward_return > 0`) → purged/embargoed folds →
  train naive/logreg/random-forest/extra-trees per fold → comparison table
  → calibration curve and permutation importance for the best model by mean
  Brier score.

### Real result (synthetic data, not a research finding)

A real end-to-end run on synthetic random-walk OHLCV data (3000 hourly
bars, mild autocorrelated drift, 5 purged folds) produced a genuinely mixed
result: `logistic_regression` had a strictly lower Brier score than
`naive_prior` on every fold (mean 0.2487 vs 0.2506), while `random_forest`
and `extra_trees` did **not** beat the baseline on this data. This is
exactly the kind of outcome the framework is built to surface — not every
model clears the bar, and the comparison harness makes that visible instead
of hiding it in an average. It is not a claim about real market data; no
model has been evaluated against real Bybit klines in this session (see
Known Issues in `docs/PROJECT_STATUS.md`).

## Implementation (Phase 13 — AI-enhanced strategy)

`src/strategies/ml_filtered.py:MLFiltered` is the first strategy that uses
a trained model, and it does so exactly the way "No LLM-as-decision-maker"
(above) requires: the model **filters**, it never decides on its own.

```
base_signal = momentum_signal(...)                # rule-based (src/strategies/signals.py)
if base_signal is None: stay flat
proba = model.predict_proba(features_at_this_bar)  # frozen scikit-learn artifact
if proba >= probability_threshold: take base_signal
else: stay flat
```

This is trade filtering (section 22's first-generation use case), composed
on top of `src.strategies.momentum.Momentum`'s exact entry rule (extracted
into `src/strategies/signals.py:momentum_signal` so both strategies share
one implementation, not two that could drift apart) — not next-candle price
prediction, and not an LLM anywhere in the decision path.

- `src/ml/model_io.py` — `save_model`/`load_model`: a model is a `.joblib`
  file plus a `.json` metadata sidecar (`ModelMetadata`: feature columns,
  symbol/timeframe, training window, git commit, ...). Loading without the
  sidecar is a hard `FileNotFoundError` — a model artifact without its
  schema and provenance is not trustworthy to use in a strategy.
- `scripts/export_ml_model.py` — fits one final model on a full date range
  and exports it. Deliberately does not evaluate the model — that's
  `src/ml/evaluation.py`'s job (Phase 12); this script only produces the
  frozen artifact a strategy can load.
- `src/strategies/ml_filtered.py` — two safety properties enforced at
  runtime, not just documented:
  1. **Schema guard**: the loaded model's `feature_columns` must exactly
     equal `src.features.pipeline.FEATURE_COLUMNS`, checked at
     construction. A model trained against a stale feature pipeline fails
     loudly instead of silently scoring misaligned columns.
  2. **In-sample guard**: per `docs/RESEARCH_METHODOLOGY.md` ("never
     evaluate a strategy on data it was optimized on"), the strategy
     refuses to trade on any bar at or before the model's recorded
     `metadata.train_end` — even if the backtest window handed to it
     happens to overlap the training window. This is enforced per-bar
     inside the strategy, not left to whoever picks the backtest dates.
  Features are recomputed each bar over a bounded rolling buffer
  (`feature_warmup_bars`, default 150) via the same
  `build_feature_matrix()` Phase 11 built and proved lookahead-free -
  known limitation: this is O(warmup window) per bar via a full pandas
  recompute, fine for backtesting, but not how a live/paper deployment
  should compute features (see Known Issues in `docs/PROJECT_STATUS.md`).
- `scripts/run_ml_strategy.py` — the dedicated CLI for `ml_filtered`
  (kept separate from `scripts/run_backtest.py`'s generic strategy list
  because `MLFilteredConfig.model_path` has no safe default — see
  `src/strategies/registry.py`).

### Real result (synthetic data, not a research finding)

Exporting a `logistic_regression` model on synthetic BTCUSDT-shaped data
(2024-01-01 to 2024-03-31) and backtesting `ml_filtered` strictly
out-of-sample (2024-04-02 to 2024-06-15, threshold 0.55) produced 30
trades and a Sharpe of -3.95, versus the unfiltered `momentum` strategy's
70 trades and a Sharpe of -5.65 over the identical out-of-sample window.
The filter reduced trade count and, on this run, reduced losses relative
to the unfiltered strategy - both strategies still lose money, as expected
on synthetic random-walk-like data with no real edge. This is a plumbing
validation, not evidence the filter helps: no model has been evaluated on
real Bybit data in this session.

## Status

Feature engineering and the research framework (Phase 11), the first
baseline model comparison (Phase 12), and the first AI-enhanced strategy
(Phase 13) are implemented — see `docs/PROJECT_STATUS.md`.
