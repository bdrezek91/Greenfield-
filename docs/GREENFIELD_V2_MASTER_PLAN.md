# Greenfield Market Intelligence v2 — Master Plan

Status: source of truth for further development

Last updated: 2026-08-21

Canonical current-core branch: **codex/stable-greenfield-v1-core**

Greenfield v2 development branch: **codex/greenfield-market-intelligence-v2**

Default branch: **main**, intentionally unchanged

## 0. How to use this document

This document is the controlling product, architecture, data, research, safety,
and delivery plan for Greenfield Market Intelligence v2. It deliberately
separates:

- **CURRENT STATE** — capabilities verified in the selected repository core;
- **TARGET STATE** — capabilities to be built and the order in which they may
  be built.

If README.md, PROJECT_STATUS.md, an older phase document, a comment, or an
implementation assumption conflicts with this plan, this plan wins until it is
changed through a reviewed pull request. Detailed documents remain useful
implementation references, but they are subordinate to this plan.

Every material change to scope, data contracts, promotion gates, risk limits,
or phase order must update this file in the same pull request. Completed work
must move from TARGET STATE to CURRENT STATE only after its Definition of Done
is met and evidence is linked in the pull request.

This is a research and engineering plan, not a promise of profitability.

## 1. Executive decision

We do not rebuild Greenfield from zero.

The branch **claude/funding-aware-multi-horizon-trend** contains the most
complete and most recent core. Git ancestry proves that it includes the full
history of both other development branches:

**main → claude/ai-trading-greenfield-gi0gr4 →
claude/ai-trading-experiment-factory-2lfl0x →
claude/funding-aware-multi-horizon-trend**

No competing work needs to be merged manually and no existing branch needs to
be overwritten or deleted.

The selected commit is:

- SHA: **5e53162e77db72aacc538acfe6526250d17d40e0**
- original branch: **claude/funding-aware-multi-horizon-trend**
- canonical preserved core: **codex/stable-greenfield-v1-core**

Greenfield v2 work starts from that exact commit on
**codex/greenfield-market-intelligence-v2**. Existing Claude branches are
historical evidence and must remain untouched.

## 2. Mission and non-negotiable principles

Greenfield is a market-intelligence, research, and controlled-execution
platform for BTC, ETH, and SOL. Its job is to determine whether an economic
hypothesis has a real, stable, executable edge, where that edge applies, and
when it has stopped working.

The objective is **edge, not the maximum backtest**.

The system must:

1. Prefer WAIT over a weak trade. No position is a valid and frequent outcome.
2. Treat fees, spread, slippage, latency, partial fills, funding, borrow or
   basis costs, and operational failure as part of the strategy.
3. Separate independent evidence from multiple transformations of the same
   price series.
4. Reject hypotheses that fail out-of-sample, stability, cost, or operational
   gates, even when their headline return looks attractive.
5. Preserve raw data and provenance so every feature, signal, backtest, and
   decision can be reproduced.
6. Keep research autonomy separate from authority to trade real capital.
7. Add AI only after the data, replay, validation, and baseline infrastructure
   are trustworthy and only when AI beats simpler baselines out-of-sample.

The initial asset universe is fixed to:

- BTCUSDT
- ETHUSDT
- SOLUSDT

Expansion to more assets requires a separate evidence-backed decision. It is
not a shortcut for finding more apparently profitable backtests.

# PART I — CURRENT STATE

## 3. Branch inventory

Inventory was performed against the four requested branches. File counts are
tracked files at each branch head.

| Branch | Head | Date | Commits ahead of main | Files | Assessment |
|---|---|---:|---:|---:|---|
| main | 15ff765 | 2026-08-14 | 0 | 1 | Initial README only; not the working project |
| claude/ai-trading-greenfield-gi0gr4 | 7110ac1 | 2026-08-16 | 39 | 194 | Broad v1 platform: data, backtest, risk, execution, ML, tests, docs |
| claude/ai-trading-experiment-factory-2lfl0x | 6d898f2 | 2026-08-17 | 69 | 246 | Superset of greenfield; adds Experiment Factory, long/short data and compaction |
| claude/funding-aware-multi-horizon-trend | 5e53162 | 2026-08-19 | 73 | 253 | Superset of Experiment Factory; newest and most complete core |

Key ancestry and delta facts:

- main is an ancestor of all three development branches.
- ai-trading-greenfield is an ancestor of ai-trading-experiment-factory.
- ai-trading-experiment-factory is an ancestor of
  funding-aware-multi-horizon-trend.
- Experiment Factory adds 30 commits and changes 67 files relative to
  ai-trading-greenfield.
- Funding-aware multi-horizon adds 4 commits and changes 17 files relative to
  Experiment Factory.
- The final four commits wire real fee, slippage, funding, and entry-delay
  scenarios into the engine; preregister and implement the multi-horizon
  funding-aware trend hypothesis; and add unit, integration, and data-integrity
  coverage.

Conclusion: **claude/funding-aware-multi-horizon-trend is the only rational
base for consolidation.**

## 4. Repository and branch policy now in force

The safe branch structure is:

- **main** — untouched legacy default branch until a separate stabilization
  decision is made.
- **codex/stable-greenfield-v1-core** — exact preserved pointer to the selected
  full core. It is the comparison base for v2 and must receive only reviewed
  stabilization fixes.
- **codex/greenfield-market-intelligence-v2** — integration branch for the v2
  program.
- short-lived feature branches — branch from the v2 integration branch and
  return through pull requests.
- existing claude branches — retained unchanged as historical records.

Required repository settings to apply manually if not already enabled:

- protect both core and v2 branches from force-push and deletion;
- require pull requests and successful checks;
- prefer squash or rebase merge for a readable history;
- require at least one human approval for execution, risk, credential, or
  promotion-gate changes;
- never commit secrets, market-data archives, models, or generated reports.

No claim is made that main is already the stable application branch. A future
PR from the preserved core to main should happen only after Phase 0 exits
cleanly.

## 5. Existing system capabilities

### 5.1 Experiment Factory

An operational research framework already exists under src/research:

- hypothesis.py — typed hypothesis contract and identity;
- queue.py — bounded hypothesis generation and variant budgets;
- orchestrator.py — full research-cycle coordination;
- evaluator.py — explicit evidence and promotion-gate evaluation;
- promotion.py — challenger, champion, degraded, and retired state handling;
- ledger.py — append-only global trial and holdout accounting;
- reporting.py — cycle and decision reports;
- locking.py — single-cycle coordination;
- config.py — versioned protocol loader.

The configured universe is BTCUSDT, ETHUSDT, and SOLUSDT. The protocol includes
bounded search, walk-forward windows, purge and embargo, a frozen holdout,
Deflated Sharpe Ratio, Probability of Backtest Overfitting, parameter
stability, adverse-cost checks, multi-symbol confirmation, PAPER gates, and
automatic retirement triggers.

The factory is valuable infrastructure and must be extended, not replaced.

### 5.2 Backtesting and robustness

Existing modules include:

- engine.py and runner.py;
- walk_forward.py;
- costs.py;
- funding.py;
- data_adapter.py;
- instruments.py;
- reports.py;
- annualization.py;
- Monte Carlo, bootstrap, Deflated Sharpe Ratio, PBO, parameter-stability, and
  portfolio analytics under src/analytics.

Currently represented:

- maker/taker fees from the instrument model;
- fee multipliers for base, adverse, and severe scenarios;
- stochastic one-tick slippage probability and multipliers;
- entry delay in bars as a latency stress;
- post-hoc perpetual funding;
- mark-to-market handling;
- walk-forward testing and frozen holdout controls.

Current realism limits:

- historical spread is not replayed tick by tick;
- slippage is a simplified one-tick probability model;
- latency is expressed in bars, not measured milliseconds and queue position;
- partial fills and fill probability are not calibrated from L2;
- funding is an explicit adjustment rather than a fully event-driven venue
  simulation;
- order-book impact and cross-venue leg risk are not modeled.

### 5.3 Current data layer

The repository currently has Bybit-only adapters and storage for:

- OHLCV klines;
- funding-rate history;
- open-interest history;
- live-polled long/short account ratio;
- live public trade tape;
- live order-book snapshot and delta processing;
- live liquidation stream;
- Parquet storage, validation, and microstructure compaction.

The current microstructure collector subscribes to depth 50 but persists a
reconstructed top-N summary: best bid and ask, mid, spread, top-side
quantities, and imbalance. It also persists individual public trades and
liquidations.

Important limitations:

- this is not yet a lossless raw L2 event lake;
- exchange sequence numbers, receipt timestamps, reconnect episodes, and raw
  payloads are not a complete replay contract;
- only Bybit is implemented;
- long/short response mapping and the live liquidation batch shape carry
  explicit verification caveats in the code;
- repository documentation reports that collection ran on a VPS, but current
  external process health and retained dataset volume were not verified by
  this repository audit.

### 5.4 Features, strategies, regimes, risk, and execution

Existing features cover price, volatility, volume, causal structure,
funding, and open-interest joins. Existing strategies include benchmarks,
momentum, trend following, breakout, mean reversion, volatility expansion,
cross-asset momentum, funding contrarian, liquidity-sweep confluence,
funding-aware multi-horizon trend, and an ML-filtered strategy.

Existing regime code covers ATR, ADX, realized volatility, moving-average
structure, and causal trend and volatility regimes.

The risk engine already enforces:

- risk per trade;
- maximum portfolio risk;
- maximum daily loss;
- maximum drawdown;
- maximum concurrent positions;
- maximum leverage;
- volatility-aware sizing.

The execution layer includes intent and adapter contracts, simulated fills,
paper execution, fill tracking, heartbeat, session recording, checkpointed
supervision, and a preflight checklist. Real LIVE order submission is
intentionally disabled.

### 5.5 Runtime and operations

Docker Compose defines services for:

- research and tests;
- autonomous research worker;
- paper session;
- Bybit microstructure collector;
- long/short-ratio collector;
- data compactor.

This is a useful 24/7 starting point, but it is not yet a complete production
data platform. There is no multi-exchange collector fleet, durable message
bus, centralized metrics and alerts, full replay audit, or tested disaster
recovery.

### 5.6 Verification snapshot and Phase 0 resolution

At the selected core there are 105 tracked source files and 99 tracked test
files. The initial 2026-08-21 audit found a false Python 3.12 compatibility
claim, a NautilusTrader 1.231 API mismatch, platform-default text encoding,
three Mypy errors, and two SIGTERM tests that terminated pytest on Windows
instead of exercising the installed handlers.

The Phase 0 branch codex/phase-0-reproducible-core resolves those local
blockers:

- support is narrowed to Python 3.11 and automation uses Python 3.11.15;
- NautilusTrader is pinned to 1.221.0;
- CI and Docker install the same uv.lock with uv 0.12.1;
- production text artifacts and manifests use explicit UTF-8;
- signal-handler tests are cross-platform and no longer kill the Windows test
  process;
- Ruff and Mypy pass cleanly;
- the full suite passes: 616 tests, 95% statement coverage, one non-blocking
  pandas FutureWarning;
- the secret hook and lockfile consistency checks pass.

GitHub Actions run 82 on commit
`d96c7d87054b6995dcdc052ec3f9fe99e174c3e8` independently passed the locked
Linux install, Ruff, Mypy, the full test suite, secret scan, Docker build, and
the full test suite inside the built image. The image embeds the immutable
source revision without copying `.git`, so experiment provenance remains
available in a production-style container.

The Phase 0 engineering baseline is therefore complete. Repository branch
protection and required-review settings remain a GitHub administrative action
because the available repository integration cannot manage protection rules;
the implementation PR remains a draft until human review. This administrative
item does not authorize bypassing PRs and does not weaken the branch policy in
section 4.

### 5.7 Documentation drift

The selected core's README.md said that ingestion, strategies, backtesting,
and ML did not yet exist, while all of them were present. The Phase 0 branch
replaces that stale description, marks PROJECT_STATUS.md as a historical log,
and adds a maintainer runbook. This master plan remains the source of truth.

# PART II — TARGET STATE

## 6. Target architecture

The target is four cooperating engines on top of one governed data platform:

1. **Directional Engine** — produces LONG, SHORT, or WAIT setups.
2. **Neutral/Arbitrage Engine** — produces hedged basis, funding, statistical,
   or cross-exchange ARBITRAGE setups.
3. **Research Engine** — generates, preregisters, evaluates, rejects, and
   promotes hypotheses.
4. **Meta Engine** — compares independent evidence and available edges,
   allocates risk, or decides not to trade.

Logical flow:

Market sources → raw immutable lake → normalized events → feature store →
regime and analog context → setup engines → Meta Engine → risk engine →
paper or execution adapters → monitoring and research ledger.

The data platform is shared. Trading engines may not maintain private,
unversioned copies of market truth.

## 7. Target data platform

### 7.1 Exchanges and sources

The target exchange layer covers:

- Bybit;
- Binance;
- OKX;
- Coinbase;
- Deribit.

Adapters must expose normalized contracts while retaining the untouched raw
payload. Exchange-specific semantics must never be silently discarded.

Initial normalized streams:

- trades and tick data;
- best bid and offer;
- L2 order-book snapshots and deltas;
- instrument metadata and trading rules;
- mark, index, and last price;
- funding rate and next-funding metadata;
- open interest;
- liquidations;
- long/short or positioning proxies where available;
- spot and perpetual prices for basis;
- options chain, quotes, trades, open interest, and Greeks where available.

### 7.2 Raw lake, normalized lake, and feature store

Use three explicit data zones:

- **Bronze / raw** — immutable exchange payload plus exchange timestamp,
  local receive timestamp, connection ID, sequence or update ID, symbol,
  channel, schema version, and ingestion version.
- **Silver / normalized** — canonical trade, book, derivative, and options
  events with exchange-specific fields retained in an extension map.
- **Gold / features** — point-in-time correct, versioned features with
  feature timestamp, maximum source timestamp, source dataset IDs, code
  version, and lookback window.

Minimum storage rules:

- append-only writes to raw partitions;
- UTC timestamps with nanosecond precision where the venue supplies it;
- partition by exchange, channel, symbol, date, and hour where appropriate;
- atomic files and compaction without rewriting uncommitted partitions;
- checksums, row counts, min and max timestamps, and schema version per file;
- quarantine rather than silent repair of corrupt or out-of-sequence data;
- retention policies documented before deletion;
- deterministic replay from raw events into normalized data and features.

### 7.3 Collector correctness contract

A collector is not done because a WebSocket connected. It must:

- capture a REST snapshot and apply deltas according to venue rules;
- detect duplicates, gaps, sequence resets, crossed books, stale streams, and
  clock drift;
- reconnect with bounded exponential backoff and jitter;
- resubscribe and rebuild book state after uncertainty;
- expose heartbeat, lag, event rate, reconnect count, gap count, and disk
  backlog;
- flush safely on normal stop and recover after process or VPS restart;
- never silently continue a book after a sequence gap;
- support deterministic raw-message replay in tests;
- complete a multi-day soak test before the data is research-eligible.

Priority order: build a trustworthy 24/7 raw market collector and accumulate
our own microstructure history before adding new strategies or AI.

## 8. Target feature domains

### 8.1 Order flow and microstructure

Required feature families:

- signed trade delta;
- cumulative volume delta and rolling CVD;
- price versus CVD divergences;
- bid and ask volume by price level;
- footprint bars;
- stacked and diagonal imbalance;
- order-book imbalance by depth band;
- microprice and spread state;
- depth, slope, convexity, replenishment, and cancellation intensity;
- absorption;
- exhaustion;
- sweep and aggressive-trade bursts;
- liquidation clusters;
- short-horizon realized impact and adverse selection.

Every feature definition must specify side convention, aggregation interval,
minimum data quality, handling of missing events, and point-in-time boundary.

### 8.2 Auction and volume context

Required features:

- session and rolling Volume Profile;
- Point of Control;
- Value Area High and Value Area Low;
- session, daily, weekly, and rolling VWAP;
- Anchored VWAP with explicitly defined causal anchor events;
- distance, acceptance, rejection, and migration around POC, VAH, VAL, VWAP,
  and AVWAP.

### 8.3 Momentum and money flow

Build a Market Cipher-like family from public mathematical concepts:

- momentum oscillation;
- wave or cycle components;
- money-flow approximation;
- volatility and trend context;
- regular and hidden divergences;
- multi-timeframe agreement.

Do not copy proprietary source code, private formulas, branding, layouts, or
reverse-engineered implementation. Every formula in Greenfield must be
documented, independently implemented, testable, and versioned.

### 8.4 Derivatives

Required derivatives features:

- open-interest level, change, acceleration, and price interaction;
- funding level, percentile, z-score, persistence, and cross-venue dispersion;
- spot-perpetual and futures basis;
- liquidation intensity and directional clusters;
- crowding and positioning proxies;
- mark-index dislocation;
- cross-exchange premium and funding opportunities.

### 8.5 Options

Deribit is the initial options reference venue. Target features:

- at-the-money implied volatility;
- volatility surface by delta and tenor;
- put-call skew and risk reversals;
- term structure and calendar shape;
- implied versus realized volatility;
- options volume and open-interest concentrations;
- gamma, vanna, and charm proxies only where inputs and methodology are
  reliable.

Options evidence is context or a separate volatility hypothesis family; it is
not automatically a directional confirmation.

### 8.6 Cross-market and later external context

First cross-market layer:

- BTC, ETH, and SOL relative strength and lead-lag;
- spot versus perpetual;
- exchange premium and fragmentation;
- stablecoin quote dislocations;
- crypto volatility and correlation structure.

Later, after core microstructure is stable:

- macro rates, USD, equities, and volatility indices;
- on-chain flows;
- ETF creation, redemption, holdings, and flow data;
- CME futures, basis, volume, and open interest.

Every external dataset needs publication-lag modeling. The value available at
decision time, not a later-revised value, is the only valid backtest input.

## 9. Regime detector and historical analog engine

### 9.1 Regime detector

The detector must classify at least:

- trending versus ranging;
- low, normal, and high volatility;
- liquid versus stressed liquidity;
- accumulation, distribution, deleveraging, and liquidation-cascade context
  where supported by data;
- risk-on, risk-off, and fragmented cross-market states.

Regime classification must be causal, probabilistic where useful, and stable
enough to avoid switching on noise. Performance must be reported per regime;
a strategy that works only in one regime must say so explicitly.

### 9.2 Historical analog engine

The analog engine retrieves prior windows using only information available at
the query timestamp. It returns:

- nearest historical states;
- similarity components by independent family;
- forward-return and risk distributions by horizon;
- sample size and uncertainty;
- regime and data-quality compatibility;
- clear warning when no meaningful analog exists.

Analog retrieval is decision support, not permission to trade. Embeddings or
ML may be added only after transparent distance baselines and leakage tests.

## 10. Signal, Setup, and Meta Engines

### 10.1 Setup contract

Every evaluated setup returns one of:

- LONG;
- SHORT;
- WAIT;
- ARBITRAGE.

The structured result must include:

- symbol or legs;
- venue or venues;
- decision timestamp and data cutoff;
- horizon;
- independent confirmation-family evidence;
- regime;
- entry zone or execution condition;
- invalidation;
- stop or hedge logic;
- expected cost range;
- expected value range and uncertainty;
- capacity or liquidity bound;
- data-quality status;
- model and feature versions;
- reason for WAIT when no setup qualifies.

### 10.2 Independent confirmation families

Confirmations are grouped into independent families:

1. price structure and auction;
2. trade flow and order book;
3. derivatives and positioning;
4. volatility and options;
5. cross-asset and cross-venue;
6. regime and historical analog context.

Rules:

- A family contributes at most one confirmation vote, regardless of how many
  indicators inside it agree.
- RSI, stochastic, MACD, moving-average distance, and other transforms of the
  same close series cannot be counted as separate independent confirmations.
- Highly correlated features within or across families must be clustered,
  down-weighted, or represented by one latent score estimated on training data
  only.
- Confirmation thresholds and weights are fit without access to holdout data.
- A directional setup requires agreement across a minimum number of genuinely
  independent families and must still clear cost and risk gates.
- Conflicting high-quality families normally produce WAIT, not forced
  averaging into a weak trade.

### 10.3 Meta Engine

The Meta Engine compares eligible outputs from Directional,
Neutral/Arbitrage, and Research-approved engines. It decides:

- which edge, if any, is currently strongest after costs;
- whether signals conflict;
- how much correlated exposure already exists;
- whether a neutral trade dominates a directional trade;
- whether uncertainty, stale data, drawdown, or operational risk requires
  WAIT;
- how to allocate the bounded risk budget.

The Meta Engine cannot override the risk engine, promotion state, kill switch,
or human-approval gates.

## 11. Directional, Neutral/Arbitrage, and Research Engines

### 11.1 Directional Engine

Combines approved setup families for LONG, SHORT, or WAIT. It is optimized for
calibrated expected value after costs, drawdown, and stability, not trade
frequency or raw directional accuracy.

### 11.2 Neutral/Arbitrage Engine

Initial research candidates:

- delta-neutral funding capture;
- spot-perpetual basis;
- cross-exchange funding dispersion;
- cash-and-carry where operationally feasible;
- low-dimensional statistical relative value.

Required additional controls:

- both-leg fill and cancellation policy;
- transfer and inventory assumptions;
- venue and counterparty limits;
- borrow, withdrawal, funding, and margin costs;
- basis convergence and leg-risk stress;
- exchange outage and liquidation scenarios.

No strategy may be called arbitrage if material directional, basis,
counterparty, inventory, or execution risk remains unbounded.

### 11.3 Research Engine

The existing Experiment Factory remains the core. Extend it to:

- preregister economic rationale, data, horizon, feature families, parameters,
  expected mechanism, failure conditions, and stop rules;
- version datasets and features;
- budget trials across the global ledger;
- run deterministic base, adverse, and severe cost scenarios;
- evaluate by regime, symbol, venue, and time;
- route only passing candidates to shadow or paper;
- publish negative results and prevent repeated mining of rejected variants;
- detect degradation and retire candidates.

Autonomous research may propose and test. It may not approve LIVE capital.

## 12. Backtest realism requirements

Every result used for promotion must model or conservatively bound:

- maker and taker fees by venue and account tier;
- spread at the decision and fill time;
- slippage as a function of side, size, volatility, depth, and urgency;
- decision, network, venue, and queue latency;
- partial fills, unfilled quantity, cancellation, and reprice behavior;
- order type and time-in-force;
- market impact and capacity;
- funding paid or received at actual event times;
- basis, borrow, hedging, and transfer costs where relevant;
- mark, index, and liquidation mechanics for derivatives;
- multi-leg execution and leg risk for neutral trades;
- data gaps, stale features, reconnects, rejected orders, and venue outages.

Backtests must consume the same normalized schemas and feature definitions as
paper and live modes. Any deliberate difference must be documented in the
experiment record.

## 13. Anti-overfitting protocol

Mandatory controls:

- chronological train, validation, and out-of-sample test;
- purging and embargo based on label horizon;
- rolling or expanding walk-forward evaluation;
- one final frozen holdout per preregistered family and protocol version;
- Monte Carlo path analysis;
- block bootstrap or stationary bootstrap that respects serial dependence;
- Deflated Sharpe Ratio;
- Probability of Backtest Overfitting;
- multiple-testing control across the global trial ledger;
- parameter perturbation and broad-plateau stability;
- minimum sample size and event count;
- performance across at least two independent assets or venues when the
  mechanism claims generality;
- sensitivity to fees, spread, slippage, delay, funding, and missing fills;
- decomposition of beta, market exposure, and concentration;
- publication of negative and inconclusive results.

Candidate multiple-testing methods include White's Reality Check, Hansen's
SPA, false-discovery-rate control, or family-wise error controls. The chosen
method and its assumptions must be preregistered before use in promotion.

No researcher may repeatedly view the final holdout, tune, and call the next
view out-of-sample.

## 14. Promotion gates

Promotion path:

**RESEARCH → OOS_CANDIDATE → SHADOW → PAPER_CHALLENGER →
PAPER_CHAMPION → LIVE_SMALL → LIVE**

General rules:

- every gate is all-of, never choose-the-best-metric;
- failure returns the candidate to research or retires it;
- no automatic jump over a stage;
- human approval is mandatory for PAPER_CHAMPION activation, LIVE_SMALL, and
  every capital increase;
- LIVE remains disabled until its phase is explicitly approved.

### 14.1 Research to OOS candidate

Requires:

- preregistration;
- complete point-in-time data and provenance;
- minimum trades or independent events;
- positive aggregate OOS result after adverse costs;
- acceptable DSR and PBO;
- stable parameter plateau;
- acceptable drawdown and tail risk;
- no single fold, trade, symbol, or regime dominance;
- no look-ahead or holdout reuse.

### 14.2 OOS candidate to shadow

Requires deterministic replay equivalence, real-time feature parity, zero
order submission, valid telemetry, and stable signal generation for a defined
observation window.

### 14.3 Shadow to paper

Requires:

- signal frequency and timing consistent with backtest tolerance;
- data freshness and completeness SLOs met;
- expected execution simulator active;
- no unexplained position, feature, or state divergence;
- human approval.

### 14.4 Paper challenger to paper champion

Keep the existing minimum-week, minimum-trade, fill-rate, slippage, drawdown,
and human-approval rules. Add reconciliation of expected versus actual spread,
latency, partial fill, and funding when those models are implemented.

### 14.5 Paper champion to LIVE_SMALL

Requires:

- a separate approved pull request enabling the exact execution path;
- dedicated API keys with least privilege and withdrawal disabled;
- fixed small capital and notional caps;
- venue, symbol, and aggregate exposure limits;
- tested hard kill switch;
- tested restart and reconciliation;
- on-call alert path and operator runbook;
- successful failure-injection exercise;
- explicit human sign-off.

### 14.6 LIVE_SMALL to LIVE

Requires a minimum observation period, sufficient independent trades,
realized execution within limits, no unexplained state mismatch, acceptable
drawdown, no safety bypass, and a new human capital decision. Scaling must be
incremental and capacity-aware.

## 15. Risk engine target

Extend the existing risk engine with:

- gross and net exposure by asset, venue, strategy, engine, and direction;
- correlated BTC-beta exposure across ETH and SOL;
- per-venue and counterparty concentration;
- margin, liquidation-distance, and collateral concentration;
- per-strategy and global daily, weekly, and peak-to-trough drawdown guards;
- order-rate, cancel-rate, notional, leverage, and open-order limits;
- stale-data and clock-drift blocks;
- kill switches at strategy, symbol, venue, and global level;
- reduce-only emergency handling;
- neutral-trade leg-risk limits;
- recovery rules that require human review after a hard safety event.

Risk rejection always wins over a signal. A process restart must not reset
loss, exposure, or kill-switch state.

## 16. 24/7 VPS operations and observability

Target services:

- one supervised collector process per exchange and channel group;
- raw writer and manifest service;
- book-state validator;
- compactor and retention worker;
- data-quality scanner;
- normalized-event builder;
- point-in-time feature builder;
- research scheduler and workers;
- shadow and paper engines;
- execution service, only after approval;
- reconciliation service;
- metrics, logs, dashboards, and alert routing.

Required observability:

- structured logs with run, connection, dataset, hypothesis, and order IDs;
- metrics for message lag, missing sequence, reconnects, write backlog, disk
  space, file age, feature freshness, research queue, order lifecycle, fills,
  exposure, PnL, drawdown, and risk rejections;
- liveness, readiness, and data-freshness health checks;
- alerts with severity, owner, runbook link, and deduplication;
- daily data-quality and system-integrity report;
- immutable audit trail for promotion and execution decisions.

Required operational tests:

- process crash and restart;
- VPS reboot;
- network partition;
- exchange disconnect and sequence gap;
- disk near-full;
- corrupt or partial file;
- duplicate messages;
- stale clock;
- delayed or rejected order;
- partial fill and one-leg fill;
- credential revocation;
- kill-switch activation.

## 17. Roadmap and exit criteria

Phases are sequential gates. Research can continue inside the existing bounded
factory, but no later production capability may bypass an unfinished
foundation phase.

### Phase 0 — Consolidate and make the core reproducible

Deliver:

- preserve the selected core and v2 branches;
- adopt this master plan;
- reconcile README and PROJECT_STATUS with reality;
- choose and document the supported Python and NautilusTrader matrix;
- fix UTF-8 file writes, current mypy errors, and Python 3.12 incompatibility
  or narrow the declared range;
- make CI deterministic from the lockfile;
- add a branch inventory note and maintainer runbook.

Exit criteria:

- clean checkout installs with one documented command;
- Ruff, Mypy, tests, and secret scan are green in CI;
- the same dependency graph is used locally, in Docker, and in CI;
- no tracked secrets or data artifacts;
- v2 branch protection and PR rules are enabled;
- README points to this document as the source of truth.

### Phase 1 — Raw collector foundation on Bybit

Deliver:

- versioned raw event envelope;
- lossless Bybit trades, L2 snapshots and deltas, liquidations, ticker,
  funding, OI, mark, and index capture;
- exchange and receive timestamps, sequence metadata, raw payload retention;
- deterministic snapshot-plus-delta book rebuild;
- manifests, atomic writes, replay CLI, and safe compaction;
- BTC, ETH, and SOL collectors under supervision.

Exit criteria:

- at least seven continuous days per symbol with documented uptime;
- every disconnect and sequence uncertainty causes a verified rebuild;
- zero silently accepted sequence gaps;
- replay produces identical normalized books and checksums;
- restart, SIGTERM, VPS reboot, and disk-backlog tests pass;
- dashboards and alerts show freshness, lag, gaps, reconnects, and storage.

### Phase 2 — Data quality, normalized lake, and feature-store contracts

Deliver:

- Bronze, Silver, and Gold layouts;
- canonical schemas and version migration policy;
- dataset catalog and point-in-time provenance;
- quality rules, quarantine, backfill, retention, and disaster-recovery
  runbooks;
- feature-store API with maximum source timestamp and code version.

Exit criteria:

- deterministic raw-to-normalized-to-feature rebuild;
- no future timestamp can enter a feature row;
- schema compatibility and contract tests pass;
- daily quality report and reproducible dataset snapshot exist;
- restore from backup is demonstrated.

### Phase 3 — Multi-exchange collection

Deliver:

- Binance, OKX, Coinbase, and Deribit adapters;
- normalized instruments and symbol mapping;
- venue-specific sequence and reconnect logic;
- spot, perpetual, futures, and initial options feeds;
- cross-venue clock and price sanity checks.

Exit criteria:

- each venue passes adapter contract and replay tests;
- BTC, ETH, and SOL coverage is continuous for supported products;
- raw venue fields remain recoverable;
- cross-venue timestamps and symbols reconcile;
- venue outage does not corrupt other collectors.

### Phase 4 — Microstructure and auction feature store

Deliver:

- CVD, delta, footprint, imbalance, absorption, exhaustion, sweep, microprice,
  depth, cancellation, and replenishment features;
- Volume Profile, POC, VAH, VAL, VWAP, and AVWAP;
- causal definitions and feature lineage;
- research notebooks or reports that describe distributions before strategy
  use.

Exit criteria:

- unit, property, replay, and no-lookahead tests pass;
- features are stable under chunking and replay boundaries;
- exchange-side and aggressor-side conventions are verified;
- realistic spread and fill feasibility are measured;
- no feature is promotion-eligible without sufficient historical coverage.

### Phase 5 — Derivatives, options, and cross-market context

Deliver:

- OI, funding, basis, liquidation, and crowding features across venues;
- Deribit IV, skew, term structure, and implied-realized features;
- BTC, ETH, SOL relative-strength and lead-lag context;
- point-in-time external publication handling.

Exit criteria:

- source-specific timestamps and revision policy are tested;
- basis and funding calculations reconcile to venue examples;
- options surface quality filters reject stale or illiquid quotes;
- feature families demonstrate distinct information, not merely correlated
  price transforms.

### Phase 6 — Regime and historical analog engines

Deliver:

- causal multi-domain regime detector;
- transparent nearest-neighbor analog baseline;
- uncertainty, sample-size, and no-analog behavior;
- regime and analog evaluation reports.

Exit criteria:

- stable walk-forward regime behavior;
- no future leakage in regime labels or analog retrieval;
- analog results reproduce from dataset and code versions;
- uncertainty is calibrated and WAIT occurs when evidence is insufficient.

### Phase 7 — Setup and Meta Engines

Deliver:

- typed LONG, SHORT, WAIT, and ARBITRAGE setup contract;
- independent confirmation-family scoring;
- correlation and duplicate-evidence control;
- Directional Engine;
- Meta Engine with portfolio and risk integration;
- reason codes and full decision audit.

Exit criteria:

- correlated indicators cannot inflate confirmation count;
- every decision is reproducible from versioned inputs;
- conflict, stale data, low confidence, and risk rejection return WAIT;
- property and scenario tests cover all decision states;
- no path bypasses risk or promotion state.

### Phase 8 — Neutral and arbitrage research

Deliver:

- funding and basis research models;
- cross-exchange opportunity and leg-risk simulator;
- inventory, margin, borrow, transfer, and venue-risk assumptions;
- paper-only multi-leg coordinator.

Exit criteria:

- opportunities remain positive after adverse all-in costs;
- both-leg, one-leg, outage, and liquidation stresses pass limits;
- no residual exposure is mislabeled as arbitrage;
- paper reconciliation proves both-leg state correctness.

### Phase 9 — Shadow and paper validation

Deliver:

- real-time shadow engine with no order permissions;
- paper execution with calibrated spread, latency, partial-fill, and funding
  comparison;
- champion and challenger dashboards;
- automated degradation and retirement review.

Exit criteria:

- required observation weeks and trade counts are met;
- live signal distribution matches research within preregistered tolerances;
- data, state, and fill reconciliation are clean;
- no risk-limit violation;
- human approval is recorded.

### Phase 10 — LIVE_SMALL, separately authorized

Deliver only after explicit authorization:

- least-privilege execution adapter;
- persistent reconciliation;
- hard kill switches and drawdown guards;
- small fixed capital envelope;
- operational runbook and incident response.

Exit criteria:

- failure-injection and recovery drills pass;
- no automatic capital scaling;
- every order is attributable to an approved setup and risk decision;
- realized execution stays inside limits for the observation period;
- any expansion requires a new human decision.

### Phase 11 — Advanced context and justified AI

Possible scope:

- macro, on-chain, ETF, and CME datasets;
- advanced analog representation;
- calibrated ML ranking or filtering;
- anomaly detection for operations and data.

Exit criteria:

- simpler baseline is established first;
- incremental OOS value survives multiple-testing and cost controls;
- explanations and failure modes are documented;
- model drift, calibration, rollback, and retirement are operational.

## 18. Test strategy

Minimum test layers:

- unit tests for formulas, parsers, state machines, risk rules, and gates;
- schema and connector contract tests per exchange;
- golden raw-message replay tests;
- property-based tests for invariants such as non-crossed book, monotonic
  sequence, conservation of quantity, and risk non-bypass;
- data-integrity tests for duplicates, gaps, ordering, timestamp drift, and
  incomplete intervals;
- look-ahead tests for every feature, label, regime, split, and analog query;
- deterministic backtest and report snapshot tests;
- integration tests from raw replay through setup and risk decision;
- execution simulation tests for latency, spread, partial fills, rejects, and
  multi-leg failure;
- chaos and restart tests for collectors and stateful services;
- performance tests for sustained peak event rate and backlog recovery;
- multi-day soak tests before production eligibility;
- security tests for secrets, permission boundaries, and LIVE denial.

Tests must validate economic invariants, not only code coverage. A passing test
suite does not substitute for out-of-sample evidence.

## 19. Definition of Done

A feature or component is done only when:

- scope and acceptance criteria are linked to a roadmap phase;
- schema, API, and failure behavior are documented;
- implementation is typed, reviewed, and lint-clean;
- unit, integration, replay, and no-lookahead tests appropriate to the change
  are green;
- data provenance and versioning are preserved;
- metrics, health checks, and alerts exist for 24/7 components;
- restart and recovery behavior is verified;
- security and risk boundaries are not weakened;
- performance is measured against an explicit target;
- docs, config examples, and runbooks are updated;
- CI is green from a clean checkout;
- evidence and known limitations are recorded in the pull request;
- this master plan is updated if current or target state changed.

A research hypothesis is done only when its result is recorded, including a
negative or inconclusive result. A strategy is not done merely because a
backtest ran or a chart looks good.

A phase is done only when every exit criterion has evidence. Partial
completion remains TARGET STATE.

## 20. What we explicitly do not do at the beginning

Until Phases 0 through 4 are complete, do not:

- add more strategy families merely to search harder;
- build an LLM trader, reinforcement-learning trader, or autonomous
  self-modifying production strategy;
- optimize thousands of indicator combinations;
- count correlated price indicators as independent confirmations;
- expand beyond BTC, ETH, and SOL;
- enable real-money LIVE execution;
- add leverage to compensate for weak expected value;
- build a polished dashboard before data correctness and alerts;
- start macro, on-chain, ETF, or CME integration ahead of raw microstructure;
- claim low-latency or HFT capability on a normal VPS;
- assume missing tick or L2 history can be backfilled;
- copy Market Cipher or any other proprietary code or private formula;
- promote on in-sample return, Sharpe alone, one symbol, one regime, or one
  lucky fold;
- silently repair or discard raw market data;
- let an autonomous research worker approve capital or bypass a human gate.

## 21. Immediate next actions

Execute in this order:

1. Merge this document into the v2 integration branch through its draft PR.
2. Complete Phase 0 dependency, UTF-8, typing, test, CI, and documentation
   repairs on focused feature branches.
3. Do not add a new strategy during Phase 0.
4. Write the v2 raw event envelope and collector acceptance tests before
   changing the running collector.
5. Deploy the improved Bybit collector for BTC, ETH, and SOL, then begin the
   measured seven-day soak required by Phase 1.
6. Review collector data quality before scheduling any microstructure
   hypothesis.

The next engineering milestone is not another signal. It is a trustworthy,
replayable, observable, 24/7 raw market dataset.
