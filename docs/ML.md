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

## Status

This document defines the target ML approach. Feature engineering lands in
Phase 6, the ML research framework in Phase 11, first models in Phase 12 —
see `docs/PROJECT_STATUS.md`.
