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

## First strategy families (Phase 6)

Three families beyond the mandatory benchmarks, chosen to be structurally
distinct from each other and from the benchmarks (not just parameter
variations of the same idea) — per section 12 of the project brief, this is
deliberately a handful, not the full list of families named there:

- `momentum` — like Trend Following, but with a dead zone: no signal unless
  the N-bar price change exceeds a threshold. Models "weak drift isn't
  worth trading."
- `breakout` — enters when price closes beyond the prior N-bar high/low
  (Donchian-style channel breakout), a structurally different trigger
  (price reaching a new extreme) from momentum/trend's reaction to drift.
- `volatility_expansion` — enters in the direction of a bar whose range
  spikes well above its recent average range, modeling a volatility-regime
  shift (a squeeze resolving into a directional move) rather than a price
  or drift signal.

All three share the same `HoldForBarsStrategy` base as the Phase 5
benchmarks (fixed-fraction sizing, fixed holding period) — the fair-
comparison framework extends unchanged to new families.

`scripts/compare_strategies.py` runs any set of registered strategies
(benchmarks and/or families) on the same data/costs, records each as an
experiment, and — for every strategy beyond the mandatory benchmarks —
reports a session-local Deflated Sharpe Ratio against `n_trials` = the
number of strategies compared in that run, as a first, rough application of
the multiple-testing awareness this document calls for (not a substitute
for the fuller roadmap: Probability of Backtest Overfitting, White's
Reality Check, when experiment volume justifies them).

## Walk-forward (Phase 7)

`src/backtesting/walk_forward.py` implements the sliding TRAIN/VALIDATION/
TEST scheme this section requires: `generate_windows()` produces windows
anchored to slide by the TEST period each step (contiguous TEST periods,
no gaps or overlaps); `run_walk_forward()` runs each window and — when a
`param_grid` is supplied — selects the best candidate on VALIDATION only,
never on TEST, using a configurable selection metric. The final reported
equity curve and trade set come from concatenating (and, for equity,
compounding into one continuous curve) the TEST periods only, per this
section's requirement.

Known, documented limitation: each TEST window runs in a fresh backtest
engine with its own starting balance, so position sizing within a window
isn't computed relative to a single continuously-compounding account
carried across the whole walk-forward run — see the module docstring.

`scripts/run_walk_forward.py` exposes this from the command line and
records the whole run as a single experiment.

## Monte Carlo (Phase 7)

`src/analytics/monte_carlo.py` resamples a strategy's trade sequence (not
equity-curve returns) with replacement into ≥10,000 alternate orderings/
compositions and reports the return distribution, drawdown distribution,
losing-streak distribution, and risk of ruin, per section 19. It's fully
vectorized over simulations, so 10,000+ simulations run in well under a
second for realistic trade counts. `scripts/monte_carlo.py` runs a strategy
and this analysis from the command line.

## Parameter robustness (Phase 7)

`src/analytics/robustness.py:flag_isolated_spikes()` implements the section-
20 diagnostic directly: given a sorted sweep of parameter values and their
metric values, it flags any point that's a local maximum far above the
average of its immediate neighbors — the "works at RSI=51.382 but not 50 or
52" pattern this section calls a symptom of overfitting. This is a building
block for parameter-grid research, not yet wired into an automated sweep-
and-plot workflow — that's future work once a specific strategy family's
parameter space is under active study.

## Market regimes (Phase 8)

`src/regimes` describes the market environment from simple, auditable
technical indicators — no AI/ML, per section 13 of the project brief:

- `src/regimes/indicators.py` — ATR, ADX (Wilder), realized volatility
  (rolling std of log returns), moving-average structure. Every function is
  a pure rolling/exponential calculation using only data up to and
  including each row; `tests/lookahead/test_regime_no_lookahead.py` proves
  it structurally (classifying a data prefix alone vs. as part of a longer
  series must produce bit-identical values up to the shared boundary).
- `src/regimes/classifier.py` — `classify_regimes()` combines moving-average
  structure + ADX into `trend_regime` (UPTREND/DOWNTREND/RANGE) and
  realized volatility vs. its own trailing window into `vol_regime`
  (HIGH_VOL/LOW_VOL). Rows before enough history has accumulated get
  `pd.NA`, never a guessed regime. Note: `vol_regime` compares against a
  *trailing* window, making it a volatility-shift detector — deep inside a
  single homogeneous-volatility stretch it naturally hovers near a 50/50
  split; the reliable signal is right after a genuine volatility change.
- `src/regimes/analysis.py` — `label_trades_with_regime()` attaches the
  regime as of each trade's entry via a backward as-of merge (never a
  future regime), and `metrics_by_regime()` computes the Phase 4 trade
  metrics separately per regime bucket — the "every strategy analyzed
  separately across regimes" requirement from section 13.
- `scripts/analyze_regimes.py` ties this together: backtest a strategy,
  classify regimes over the same period, and report/record a per-regime
  performance breakdown.

## Risk engine (Phase 9)

`src/risk/engine.py:RiskEngine` is the gatekeeper between a strategy's
signal and an actual order, per section 29 of the project brief: the
strategy decides direction, the risk engine decides whether to enter and
how large. It's stateful (tracks each open position's committed risk
fraction and the day's realized PnL itself) and deliberately decoupled from
NautilusTrader - generic `(price, equity, timestamp)` inputs, testable
without a running backtest engine. It enforces, in this order: max
concurrent positions, max daily loss (resets each UTC day), max drawdown
from peak equity, then sizes the approved trade by `risk_per_trade` (or
volatility-target-scaled risk, if configured), the remaining
`max_portfolio_risk` budget, and `max_leverage`.

All benchmark and family strategies (Phase 5/6) now delegate entry approval
and sizing to a `RiskEngine` instance instead of a bare fixed-fraction
calculation - `src/strategies/base.py`'s `HoldForBarsStrategy` and
`buy_and_hold.py` construct one from their config's risk fields. Scope
note: `max_concurrent_positions`/`max_portfolio_risk` only see positions
opened by that same strategy instance's own `RiskEngine` - there's no
shared, cross-strategy risk budget yet (see the module's docstring).

## Portfolio (Phase 9)

`src/portfolio/aggregation.py` combines independently-run, single-symbol
backtest results into portfolio-level views, per section 30: a combined
equity curve (each symbol's own PnL summed onto a shared timeline),
pairwise return correlation, concentration (Herfindahl-Hirschman Index of
trade notional by symbol), portfolio drawdown, and portfolio exposure
(union of open-position intervals across symbols). This is post-hoc
aggregation of independently-backtested symbols, not one simultaneous
multi-instrument strategy sharing a single live account/risk budget - see
the module's docstring for that scope boundary, the same one the risk
engine flags for cross-instrument risk.

`scripts/portfolio_backtest.py` runs one strategy across several symbols
and reports/records the aggregated view.

## Paper trading (Phase 10)

Per the project brief section 32: after research passes, paper trading
compares expected fills against actual (simulated/live-market) fills,
checking latency, slippage, rejected signals, and data issues.

- `src/execution/mode.py` enforces the `RESEARCH`/`BACKTEST`/`PAPER`/`LIVE`
  gate concretely (Phase 1 only documented it) — `LIVE` requires a second,
  explicit environment variable, and no live-trading path exists yet
  regardless.
- `src/execution/intent.py`/`adapter.py` formalize section 31's
  `SIGNAL -> RISK -> ORDER INTENT -> EXECUTION -> EXCHANGE` pipeline as an
  `OrderIntent`/`ExecutionAdapter` boundary — swapping the adapter never
  requires touching strategy or risk code.
- `src/execution/fill_tracking.py` implements the expected-vs-actual
  comparison directly: signed slippage (adverse-positive regardless of
  side), latency, and structural data-issue detection (negative latency,
  zero/partial fills).
- `src/execution/paper_node.py` runs the *same, unmodified* `Strategy`
  classes from Phases 5/6 live against Bybit's testnet via NautilusTrader's
  native Bybit adapter — the direct payoff of the Phase 0 architecture
  decision (one engine, one strategy codebase, backtest through paper).
- `src/execution/simulated_adapter.py` + `backtest_bridge.py` let the same
  `FillTracker` machinery be exercised fully offline: a backtest's own
  trades become `OrderIntent`s, replayed through a seeded simulated
  adapter, for dry-run testing and demonstration without any network
  dependency (`scripts/paper_trade.py` is the live Bybit-testnet path;
  the dry-run pipeline is exercised directly in
  `tests/integration/test_paper_dry_run.py`).

Known limitation: this project's development sessions run under a network
policy that blocks `api.bybit.com`, so live Bybit testnet connectivity has
not been exercised end to end — only construction of the trading node
(strategy registration, client factory wiring) up to but not including an
actual connection attempt. See `docs/VPS_DEPLOYMENT.md` and
`docs/PROJECT_STATUS.md`.

## Status

This document defines the methodology. Experiment tracking, the metric set,
first-pass multiple-testing diagnostics (Phase 4), the four mandatory
benchmarks (Phase 5), the first three strategy families (Phase 6),
walk-forward + Monte Carlo + parameter-stability diagnostics (Phase 7),
market regime classification (Phase 8), the risk engine + portfolio
aggregation (Phase 9), and the paper trading execution pipeline (Phase 10)
are implemented — see `docs/PROJECT_STATUS.md` for what's next.
