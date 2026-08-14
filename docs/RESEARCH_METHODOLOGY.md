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

## Status

This document defines the methodology. Implementation (experiment tracking
store, walk-forward runner, Monte Carlo engine, overfitting diagnostics)
lands in Phases 4 and 7 — see `docs/PROJECT_STATUS.md`.
