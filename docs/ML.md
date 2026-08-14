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

No `scikit-learn`/`lightgbm` dependency is installed yet - consistent with
this project's practice of not installing a dependency before code uses it
(see e.g. `vectorbt`'s deferral through Phases 3-6). Phase 12 activates the
`ml` extras group in `pyproject.toml` when it adds the first real models.

## Status

This document defines the target ML approach. Feature engineering and the
research framework (Phase 11) are implemented; first models land in
Phase 12 — see `docs/PROJECT_STATUS.md`.
