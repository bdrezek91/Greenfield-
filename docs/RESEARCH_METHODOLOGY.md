# Research Methodology

The goal of this project is not the highest backtest profit. It is a system
that can answer: do we have a real edge, how large is it, how stable, under
what market conditions does it work, when does it stop working, what does
out-of-sample and forward-test look like, and does AI actually improve
anything. This document is the operating methodology that keeps every
experiment honest.

## Core rules

1. **Never evaluate a strategy on the data it was optimized on.**
   Pipeline: `TRAIN -> VALIDATION -> OUT OF SAMPLE -> FORWARD/PAPER`.
2. **No lookahead, ever.** A feature at time `t` may only use information
   available up to `t`. Enforced by `tests/lookahead/`.
3. **Benchmarks first.** Before judging any strategy, it must be compared
   against Buy & Hold, Random Entry, Simple Trend Following, and Simple Mean
   Reversion, run through the *same* pipeline (same costs, same risk engine).
   Random Entry in particular answers: is this strategy actually better than
   random entries under similar risk management?
4. **Stable parameter regions, not single best parameters.** A strategy that
   only works at `RSI = 51.382` and breaks at 50/52 is treated as a symptom
   of overfitting, not a discovery.
5. **Multiple-testing awareness.** Testing hundreds of strategy variants
   means some will look good by chance. Roadmap: bootstrap and Deflated
   Sharpe Ratio first (Phase 4), then Probability of Backtest Overfitting and
   White's Reality Check as the experiment volume grows.
6. **Rejection is a valid, expected outcome.** If an experiment doesn't work:
   reject it. If a strategy has no edge: reject it. If ML doesn't improve
   results: reject the ML. If results are ambiguous: label them
   `INCONCLUSIVE`, don't keep tuning until the chart turns green.

## Experiment tracking

Every experiment (backtest run, walk-forward run, ML model) is recorded with:

`experiment_id, git_commit, dataset_version, date_range, symbols, timeframes,
strategy_version, parameters, fees, slippage, funding assumptions, metrics,
timestamp`

Experiment IDs are sequential: `EXP-000001`, `EXP-000002`, ... The concrete
storage mechanism (flat files vs. lightweight DB vs. mlflow) is a Phase 4
decision — this document defines the required fields regardless of backend.

## Walk-forward

Automatic sliding-window framework, e.g. `TRAIN 12 months / VALIDATION 3
months / TEST 3 months`, window advanced repeatedly. The final reported
equity curve is assembled from consecutive `TEST` periods only — never from
in-sample or validation periods. Designed in Phase 7.

## Metrics (minimum set)

Trades, Net Return, CAGR, Win Rate, Average Win, Average Loss, Expectancy,
Profit Factor, Sharpe, Sortino, Calmar, Max Drawdown, Ulcer Index, Average R,
Median R, Longest Losing Streak, Exposure/Time in Market, Turnover, Fees,
Funding Costs, and MAE/MFE where applicable.

## Monte Carlo

For strategies that pass basic validation: minimum 10,000 simulations,
analyzing return distribution, drawdown distribution, risk of ruin, and
losing-streak distribution. Implemented in Phase 7.

## Implementation (Phase 4)

- `src/analytics/experiment.py` — `ExperimentRecord` (the fields listed
  above) and `ExperimentStore`: an append-only JSON Lines log at
  `reports/experiments/experiments.jsonl` (generated output, gitignored —
  same principle as raw data) with sequential `EXP-NNNNNN` IDs.
  `capture_git_commit()` and `fingerprint_dataset()` fill in the
  `git_commit`/`dataset_version` fields automatically.
- `src/analytics/metrics.py` — computes the full metric set from two
  generic, engine-independent contracts (a `trades` DataFrame and an
  `equity` series — see the module docstring for the exact columns
  expected): Trades, Net Return, Win Rate, Average Win/Loss, Expectancy,
  Profit Factor, Sharpe, Sortino, Calmar, Max Drawdown, Ulcer Index,
  Average/Median R (when the strategy supplies `r_multiple`), Longest
  Losing Streak, Exposure, Turnover, Fees, Funding Costs, and MAE/MFE
  (when supplied). CAGR/Sharpe/Sortino/Calmar/Max Drawdown/Ulcer come from
  the equity curve; the rest from individual trades.
- `src/analytics/robustness.py` — `bootstrap_metric` (generic resampling,
  the same mechanism Phase 7's 10k+-simulation Monte Carlo will use) and
  `deflated_sharpe_ratio` (Bailey & López de Prado's DSR: the probability
  an observed Sharpe ratio reflects genuine skill rather than the best of
  `n_trials` strategies tested, adjusted for the return series' skew and
  kurtosis).
- `src/analytics/report.py` — renders an `ExperimentRecord` to a Markdown
  file under `reports/experiments/<experiment_id>.md`.

Probability of Backtest Overfitting and White's Reality Check remain on the
roadmap for a later phase, once experiment volume makes them worth the
implementation cost.

## Benchmarks (Phase 5)

`src/strategies` implements the four mandatory benchmarks as NautilusTrader
strategies: `buy_and_hold`, `random_entry`, `trend_following`,
`mean_reversion`. Three of them (everything but Buy & Hold) share a common
base (`src/strategies/base.py`) that enforces identical fixed-fraction
position sizing and a fixed holding period - so the *only* thing that
differs between them is the entry signal, which is the fair-comparison
requirement this section calls for. Position sizing here is an explicit,
temporary placeholder (`src/strategies/sizing.py`) standing in for the real
Risk Engine (Phase 9).

`scripts/compare_benchmarks.py` runs all four benchmarks against the same
data/costs, computes the Phase 4 metric set for each via
`src/backtesting/reports.py` (which adapts NautilusTrader's positions/
account reports into the generic trades/equity contracts `src/analytics/
metrics.py` expects - cross-verified in tests against the engine's own
`realized_pnl`), and records each run as an experiment.

## Status

This document defines the methodology. Experiment tracking, the metric set,
first-pass multiple-testing diagnostics (Phase 4), and the four mandatory
benchmarks (Phase 5) are implemented; the walk-forward runner and full-scale
Monte Carlo engine land in Phase 7 — see `docs/PROJECT_STATUS.md`.
