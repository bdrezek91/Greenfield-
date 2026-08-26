# Greenfield Market Intelligence v2 — Master Plan

Status: source of truth for further development

Last updated: 2026-08-22

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

SOL remains in the full data, research, backtest, paper, and signal universe,
including ATAS-like order-flow and Market Cipher-like features. Its allocation
and risk tier is capped at **MEDIUM**: no strategy, Meta Engine decision, or
future execution mode may promote SOL to a HIGH risk/allocation tier without a
separate evidence-backed change to this source-of-truth document and explicit
human approval. This cap does not reduce raw collection fidelity.

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

The Phase 1 feature branch `codex/phase-1-raw-collector-foundation` now adds a
versioned raw-event and manifest contract, exact WebSocket-text retention,
atomic immutable Parquet parts, strict Bybit depth-50 and ticker replay,
non-destructive compaction, health/Prometheus/history outputs, and three
isolated supervised BTC/ETH/SOL services. A 2026-08-21 public-feed smoke test
captured and deterministically replayed 1,276 messages with zero drops or
sequence uncertainties. This implementation remains **TARGET STATE**, not a
completed Phase 1, until the seven-day VPS soak and every exit criterion in
section 17 pass. Detailed evidence and operation instructions are in
`docs/RAW_COLLECTOR_V2.md`.

A fail-closed capacity forecaster now projects the seven-day raw footprint from
a finalized, drained, lossless BTC/ETH/SOL sample, applies a mandatory 4x burst
factor, adds the 5 GiB runtime reserve, and compares the result with free bytes
on the actual target filesystem. The preserved smoke sample requires about
77.59 GiB under that stressed model. This is planning evidence only; it does
not weaken or replace the seven-day acceptance run.

The current operational checkpoint and exact continuation instructions are in
`docs/PHASE_1_HANDOFF.md`. On 2026-08-22 the isolated VPS checkout was verified
at commit `e83b15a54f9d21d5749b4ec4b1bfeaf77ba03328`; the host was safely rebooted
onto kernel `6.8.0-138-generic`, Docker recovered, and the unrelated protected
Multiplekser workload returned healthy without Greenfield modifying it. The
post-reboot preflight passes the host-restart, runtime, repository, storage
semantics, Bybit connectivity, clock, secret, and monitoring-bind checks. It
now has an off-host HTTPS alert destination verified end to end. A dedicated
100 GB OVH volume is mounted at `/opt/greenfield-v2/data`; preserved Bronze is
never to be deleted to manufacture capacity. The original 2026-08-22 soak is
historical evidence only: its source commit is obsolete and its audit contains
heartbeat gaps above 30 seconds.

On 2026-08-25 a clean detached checkout at commit
`2a7588f61049c327c2fb7822ed55a2bf0e22ff8c` passed fresh VPS preflight and a
4x-burst capacity forecast with a 5 GiB runtime reserve. The first attempted
marker was retained but invalidated because old restart-managed containers
overlapped its boundary. After those exact legacy services were stopped
gracefully (`received == written`, queue zero), the formal immutable session
`phase1-20260825t164933z` started. Its early machine audit shows all three
BTC/ETH/SOL collectors healthy, zero drops, zero sequence uncertainties and
approximately five-second heartbeat gaps; the only expected failure is that
the required 604,800 seconds have not elapsed. This is an **in-progress soak**,
not Phase 1 acceptance. The pinned collector containers and the existing
monitoring stack must not be restarted or upgraded during the uninterrupted
window. Recovery drills happen after the seven-day audit snapshot so their
intentional `stopped` health records cannot contaminate that window.

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

CURRENT STATE checkpoint (2026-08-23, Phase 2 branch):

- a shared portfolio risk budget now clamps or rejects entries across gross,
  net, symbol, venue, strategy, engine, correlated-beta, committed-risk, and
  open-position limits;
- correlation evidence is explicit and fail-closed: every other open symbol
  must be covered, while correlated BTC/ETH/SOL exposure consumes one shared
  bucket;
- UTC daily-loss and peak-to-trough drawdown guards plus a reasoned global
  kill switch are non-overridable entry blocks;
- approved decisions are single-use and bound to the exact proposal, so a
  decision cannot be replayed for another setup or forged outside the engine;
- exposure, PnL, equity peak, UTC loss day, and kill-switch state have a typed,
  validated snapshot/restore contract plus an atomic, fsynced, checksummed JSON
  state store. The shadow/paper runtime must make this store mandatory around
  every exposure-changing transition before the VPS path is restart-safe;
- weekly guards, scoped strategy/symbol/venue kill switches, margin and
  collateral aggregation, order/cancel-rate limits, runtime state-store wiring,
  and reduce-only recovery remain TARGET STATE and are not represented as done.

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

The planned Operator UI is a separate read-only domain console, specified in
`docs/OPERATOR_UI_SPEC.md`. Its first release exposes versioned status,
collector/data-quality, market intelligence, evidence, decision, research,
SHADOW/PAPER, risk, and audit views without any execution or control endpoint.
It is implemented only after the real-time evidence-to-SHADOW path and alerts
are stable; Grafana remains the technical monitoring surface. This preserves
the rule against building a polished dashboard before data correctness.

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

Implementation status on `codex/phase-1-raw-collector-foundation`:

- raw envelope, atomic storage, manifests, strict replay, safe mirror
  compaction, BTC/ETH/SOL supervision, health history, and container
  healthchecks are implemented and locally tested;
- a 5 GiB hard runtime storage reserve prevents initial subscription and stops
  active collection fail-closed before `ENOSPC`, with a dedicated health error,
  metric, and critical alert;
- a machine-readable capacity forecast fails closed unless its sample is
  finalized, drained, lossless, covers baseline BTC/ETH/SOL streams, and its
  4x stressed seven-day projection plus reserve fits the target filesystem;
- a version-pinned Prometheus, Alertmanager, node-exporter, Grafana, and durable
  vendor-neutral alert receiver is implemented as an isolated Compose profile,
  with checked-in rules and an operations dashboard;
- a fail-closed acceptance gate now combines and hashes soak, strict replay,
  alert-delivery, recovery-drill, incident-reconciliation, and explicit operator
  approval evidence; its presence does not replace performing those checks;
- a target-host preflight now fails before the soak on wrong/dirty commits,
  insufficient or non-atomic storage, Docker/Compose faults, Bybit DNS/TLS/WS
  failure, clock skew, a pending host reboot, unsafe monitoring exposure, or
  missing off-host alerts;
- an exclusive soak-session marker binds the seven-day window to UTC, the exact
  commit, fresh qualified preflight, fresh qualified capacity forecast,
  collector set, and hashes of every runtime configuration; it rechecks live
  free bytes, while the bundle and final gate verify the same capacity report;
  rolling or overwritten start times cannot satisfy acceptance;
- all five recovery drills now have immutable machine-verifiable report
  contracts; the final gate verifies each report's soak session, commit,
  operator, timestamp, replay checksum, passed checks, and file SHA-256 instead
  of trusting an operator checkbox;
- a portable evidence-bundle manifest now content-addresses the session, soak,
  replay, alerts, off-host receipt, secret-free runtime configuration, and five
  drill reports; the final gate re-hashes every file and cross-checks the
  artifacts it actually evaluates before accepting operator approval;
- off-host alert acceptance now requires one correlated immutable report that
  proves the same event ID in the durable receiver journal, forward-success
  record, and exported external receipt, bound to the soak session, deployed
  commit, named operator, and a bounded delivery delay;
- every reconnect and sequence-uncertainty reconciliation is now backed by a
  separately hashed artifact and a matching `incident/<ID>` entry in the
  immutable bundle; path-only, changed, duplicate, or missing evidence fails;
- a short live public-feed smoke test passed and revealed two defects that
  were fixed before the soak;
- the isolated target VPS checkout, Python 3.11 runtime, Docker model, atomic
  data path, Bybit DNS/TLS/WebSocket connectivity, clock synchronization, and
  safe loopback-only monitoring bind were verified at commit `e83b15a`;
- the target VPS was rebooted successfully onto kernel `6.8.0-138-generic` and
  no longer reports a pending reboot; this maintenance reboot is not the
  immutable in-session recovery drill required by the Phase 1 gate;
- Phase 1 is currently blocked by one deliberate preflight failure: no
  configured off-host HTTPS alert destination; the dedicated data volume and
  operator-approved 90 GiB start gate resolve the capacity blocker;
- the seven-day soak, VPS reboot/backlog/restore drills, persistent metrics
  retention, and end-to-end off-host alert delivery still require measured VPS
  evidence before exit.

### Phase 2 — Data quality, normalized lake, and feature-store contracts

Current implementation checkpoint (2026-08-22):

- a seven-day Bybit REST backfill for BTCUSDT, ETHUSDT, and SOLUSDT is stored
  separately on the VPS: six kline intervals, funding, 5-minute OI, and the
  most recent 500 five-minute long/short samples per symbol;
- a deterministic tiered backfill plan now covers BTC/ETH/SOL on Bybit,
  Binance, and OKX: 180 days at 1m, two years at 5m, three years at 15m,
  roughly five years at 1h/4h/1d, plus provider-bounded Bybit funding/OI;
  execution is resumable and opt-in, while missing pre-listing or unavailable
  microstructure history is never synthesized;
- the REST backfill is explicitly hybrid evidence, not a substitute for the
  concurrently running live trades/L2/liquidation collectors;
- deterministic Bronze-to-Silver normalization exists for every L2 level,
  public trade, all-liquidation event, and ticker field, with exact decimal
  text and lineage to the immutable raw event and payload hash;
- immutable Silver Parquet parts, per-source manifests, checksums,
  idempotent rebuilds, and a verified lake-normalization CLI are implemented
  on the Phase 2 feature branch but are not deployed into the active Phase 1
  soak;
- point-in-time closed-candle and feature provenance contracts, quarantine
  overlays, daily quality reports, and reproducible dataset catalog snapshots
  are implemented on the Phase 2 feature branch;
- the immutable versioned Gold feature writer/API rejects future, duplicate,
  null, infinite, and unversioned feature rows before storage;
- schema migration, scheduled VPS quality/catalog jobs, and restore evidence
  remain TARGET STATE.

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

Current implementation checkpoint (2026-08-22):

- canonical spot, perpetual, future, and option identities now resolve exact
  `(exchange, market_type, venue_symbol)` keys without symbol guessing;
- point-in-time cross-venue snapshots select only already received, non-stale
  quotes and expose clock age, median price deviation, and outlier evidence;
- Binance USD-M aggregate-trade and diff-depth messages now enter a lossless
  raw envelope; a replay gate validates REST-snapshot bridging and strict
  `U/u/pu` continuity before any order-book materialization;
- Silver schema v2 and the Binance normalizer retain first/final/previous
  update IDs, exact decimals, aggressor-side trades, ticker metrics, and raw
  lineage through immutable Parquet round trips;
- OKX public books, trades, and ticker messages now enter a lossless raw
  envelope; the replay gate requires a fresh snapshot per connection and
  enforces strict `seqId/prevSeqId` continuity. It intentionally does not use
  the deprecated JSON order-book checksum;
- the OKX Silver normalizer retains exact decimals, taker-side trades,
  first/previous/final book sequence lineage, ticker metrics, and immutable raw
  lineage through the same verified multi-venue pipeline;
- Coinbase Advanced Trade L2, market-trade, and ticker messages now enter a
  lossless raw envelope; ambiguous multi-product envelopes remain recoverable
  in Bronze but fail closed before Silver instead of receiving a guessed
  symbol;
- the Coinbase L2 gate requires a connection-scoped snapshot and consecutive
  per-product `sequence_num` values. Silver preserves exact levels and converts
  Coinbase's documented maker-side trade field into canonical aggressor side;
- Deribit option/future/perpetual books, trades, and ticker notifications now
  enter a lossless JSON-RPC envelope. Book replay requires the first snapshot
  and strict `change_id/prev_change_id` continuity per connection;
- Deribit Silver preserves book and trade sequence lineage plus option ticker
  fields including bid/ask/mark IV, underlying, open interest, and canonical
  nested Greeks; topic/payload instrument disagreement fails closed;
- live Binance/OKX/Coinbase/Deribit transports remain TARGET STATE and must
  satisfy these contracts before deployment.

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

Current implementation checkpoint (2026-08-22):

- normalized trade tape produces causal aggressor buy/sell volume, signed
  delta, stateful CVD, trade count, volume, and VWAP;
- normalized L2 snapshot/delta rows produce strict stateful best bid/ask,
  spread, mid, microprice, depth-band quantities, and book imbalance;
- both accumulators are stable when the identical replay stream is split at
  arbitrary row boundaries; L2 gaps/regressions and deltas before a snapshot
  fail closed;
- the order-flow outputs pass the point-in-time Gold writer contract;
- tick-size-aware footprint levels, diagonal and stacked imbalance, causal
  VWAP/AVWAP, and contiguous Volume Profile value areas with POC/VAH/VAL are
  implemented from the normalized trade tape;
- causal L2 size-change accounting now separates additions, cancellations,
  and short-window replenishment; trade tape rules identify multi-level
  sweeps, absorption stalls, and weakening-aggression exhaustion at new
  extremes;
- regular and hidden price/momentum divergence uses delayed confirmed pivots,
  so evidence appears only after the required right-hand bars exist;
- price/CVD divergence is emitted as one explicitly named order-flow
  confirmation family rather than several independent votes;
- an independent Market-Cipher-like feature family now combines standard EMA
  normalized momentum, rolling volume-weighted money flow, Wilder RSI, and
  the confirmed divergence layer without proprietary code or private formulas;
- richer cancellation/replenishment distributions remain TARGET STATE.

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

Current implementation checkpoint (2026-08-23):

- the first causal derivatives context computes mark/index basis, OI change,
  annualized funding context, long/short positioning, liquidation imbalance,
  and a single composite crowding score from point-in-time aligned inputs;
- correlated derivatives components remain one confirmation family and are
  not counted as independent votes;
- Deribit option raw/Silver contracts now retain the IV, Greeks, underlying,
  open-interest, book, and trade evidence required by the surface builder;
- a causal point-in-time option surface now rejects stale, future, illiquid,
  crossed, wide-spread, and underlying-inconsistent quotes, selects only the
  latest available observation per instrument, and refuses to mix venues;
- the surface exposes two-sided ATM IV, 25-delta put/call IV, skew, risk
  reversal, butterfly, term-structure slope, implied-minus-realized
  volatility, and OI concentrations with source timestamp and rejection
  lineage;
- these options features remain context/a separate volatility family and do
  not become extra directional confirmations;
- a synchronized causal cross-market panel now supplies BTC/ETH/SOL relative
  strength, spot-perpetual basis, cross-sectional rank, market breadth,
  dispersion, benchmark correlation, and benchmark-lag correlation. Duplicate,
  incomplete, or future-sourced panels fail closed;
- live Deribit surface materialization, multi-venue basis aggregation, CME,
  ETF, macro, and on-chain context remain TARGET STATE.

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

Current implementation checkpoint (2026-08-23):

- the original causal ADX/moving-average trend and realized-volatility shift
  labels remain available as the transparent price baseline;
- a multi-domain detector now consumes explicitly point-in-time-aligned price,
  volatility, spread/depth, signed-delta, OI, liquidation, breadth,
  cross-asset-dispersion, and benchmark-return evidence;
- it emits separate trend/range, LOW/NORMAL/HIGH volatility,
  LIQUID/STRESSED liquidity, ACCUMULATION/DISTRIBUTION/DELEVERAGING/
  LIQUIDATION_CASCADE flow, and RISK_ON/RISK_OFF/FRAGMENTED cross-market
  candidates and confirmed regimes;
- rolling quantiles and z-scores use only current-and-prior observations. A
  configurable consecutive-observation gate stabilizes label changes, while
  missing evidence clears state instead of carrying a stale classification;
- source timestamps, duplicate observations, finite/range constraints, warmup,
  independent per-asset state, switch confirmation, and appended-future
  invariance have direct tests;
- a transparent nearest-neighbor analog baseline now standardizes from eligible
  history only, computes distance once per independent family, and forbids one
  feature from appearing in several family components;
- the maximum requested forward horizon is an automatic embargo: every
  neighbor's entire return/adverse/favorable path must end no later than the
  query state. Selected neighbor outcome windows cannot overlap and inflate
  effective sample size. Same-regime and minimum-quality compatibility are
  explicit gates;
- results retain neighbor and per-family distances, forward-return quantiles,
  positive probability, adverse/favorable quantiles, sample size, dataset/code
  versions, and a deterministic search-configuration fingerprint;
- insufficient history, query quality, compatible history, or similar sample
  returns an explicit non-meaningful/no-analog warning with no distribution;
- walk-forward analog evaluation reports and empirical uncertainty calibration
  remain TARGET STATE.

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

Current implementation checkpoint (2026-08-23):

- a typed setup boundary now represents LONG, SHORT, WAIT, and ARBITRAGE with
  declared targets/legs, decision and cutoff timestamps, horizon, regimes,
  entry/invalidation/risk logic, cost and after-cost value ranges, capacity,
  data quality, versions, evidence, and reason codes;
- actionable legs must belong to declared targets; LONG/SHORT sides and
  opposing ARBITRAGE legs are structural invariants, while WAIT can never
  contain executable legs and always carries a reason;
- the first Directional Engine admits at most one aggregate evidence object
  from each of the six independent confirmation families. Multiple RSI/MACD/
  stochastic/MA-style components inside price evidence therefore remain one
  vote;
- stale or low-quality evidence, conflicting families, insufficient family
  count, non-positive conservative edge after costs, failed data quality,
  zero capacity, kill switch, operational health, promotion, or risk gate all
  return WAIT;
- future evidence and stale decision-time cutoffs fail closed, and the engine
  cannot turn a rejected gate into an execution leg;
- the first Meta Engine ranks only research-approved actionable setups by
  after-cost value penalized for uncertainty; opposing LONG/SHORT candidates
  on the same symbol force WAIT, while a stronger neutral setup can dominate a
  directional one;
- allocation is the minimum of setup capacity, available risk, gross exposure,
  per-symbol exposure, and correlated-exposure room. Missing correlation
  evidence fails closed instead of being assumed zero;
- global kill switch, operational health, portfolio risk, zero budget, stale/
  future setup, failed setup quality, and promotion status cannot be
  overridden. Candidate rankings and rejection reasons remain in the audit;
- live portfolio wiring and Neutral/Arbitrage engine remain TARGET STATE.

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

Current implementation checkpoint (2026-08-23):

- a typed Neutral Engine evaluates funding capture, spot-perpetual basis,
  cross-exchange funding, and cash-and-carry mechanisms;
- every opportunity contains opposing venue legs, a declared atomic-or-cancel
  or hedge-on-partial policy, a maximum unhedged window, explicit inventory/
  borrow/transfer state, venue health, capacity, margin buffer, and liquidation
  distance;
- all-in adverse costs aggregate fees, spread, slippage, funding payments,
  borrow, transfer, and orphan-leg hedge costs. ARBITRAGE requires the
  conservative lower edge to remain positive after their adverse bound;
- derivatives and cross-market evidence are both required and each remains a
  single independent-family vote with freshness, quality, and support gates;
- unavailable legs, unconfirmed borrow, non-prefunded transfer dependency,
  unhealthy venue, excessive orphan/outage/liquidation stress, inadequate
  margin/liquidation distance, or excessive unhedged time returns WAIT;
- this `ARBITRAGE` action means a bounded paper-research opportunity, never a
  claim of risk-free profit. Live venue coordination and reconciled paper fills
  remain TARGET STATE.

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

CURRENT STATE checkpoint (2026-08-23, Phase 2 branch):

- the deterministic offline PAPER adapter now models spread, adverse
  slippage, taker fees, funding, latency jitter, partial fills, and rejection
  probability under seeded, reproducible assumptions;
- every simulated fill preserves its explicit cost decomposition and the fill
  tracker reports partial-fill count, mean fill ratio, and mean all-in cost in
  basis points alongside latency, rejection, and slippage;
- defaults remain backward-compatible and cost-free only for legacy tests;
  every real shadow/paper run must provide a named calibrated assumption set;
- a dedicated `SHADOW` mode and no-order coordinator now consume Meta
  Decisions, validate an exact one-to-one setup-leg mapping, stage every entry
  through the portfolio Risk Engine, and persist virtual exposure before
  acknowledging eligibility;
- shadow restarts require a matching dataset, code, and configuration context,
  a checksummed risk checkpoint, and a reconciled append-only, fsynced,
  SHA-256-chained audit journal. Any tampering, duplicate observation, or
  state/audit mismatch fails closed;
- virtual exits persist realized PnL into the same daily-loss and drawdown
  state. The coordinator imports no execution adapter and records every
  eligible result explicitly as `ELIGIBLE_NO_ORDER`;
- causal execution calibration now joins every paper observation to the latest
  same-symbol/same-venue top-of-book quote at or before its decision timestamp;
  source sequence deterministically resolves equal timestamps, while missing,
  stale, duplicate, or future evidence fails closed;
- per-market empirical calibration records rejection and partial-fill rates
  plus p50/p95/p99 spread, touch-relative adverse slippage, latency, fees, and
  conservative positive funding costs. Sample count, join quality, recency,
  dataset fingerprint, and model version are mandatory gates;
- named BASE, ADVERSE, and SEVERE scenarios now translate those observed
  distributions into seeded PAPER assumptions. Favorable fee/funding credits
  are floored at zero rather than used to manufacture edge;
- a supervised SHADOW event loop now uses a durable SQLite WAL queue with
  idempotent enqueue, expiring leases, crash recovery, bounded exponential
  retry, and dead-letter handling. Loop progress, heartbeat, failure streak,
  and queue depth survive process restarts and publish atomic JSON plus
  Prometheus metrics;
- an unrecovered failure streak activates and durably audits the portfolio
  kill switch before further entries. An audit-written but unacknowledged item
  is recovered idempotently after restart, without replaying its decision;
- an immutable, checksummed `ShadowWork` payload store now backs the durable
  queue: a single allowed base directory, an unambiguous `shadow-work:`
  scheme with no path separators (traversal is structurally impossible), a
  read path that refuses to follow symlinks, atomic fsynced writes with
  read-only (0o440) files afterward, SHA-256 payload checksums, a mandatory
  schema version, a fail-closed future-timestamp guard, and idempotent writes
  keyed by observation id. A generic reflection-based (de)serializer covers
  the full `MetaDecision`/`SetupDecision`/portfolio-proposal dataclass graph
  so the store tracks those contracts without hand-mapped fields. A producer
  helper (`enqueue_shadow_work`) writes the payload then enqueues it
  idempotently in one call, and `ShadowWorkStore.load` plugs directly into
  `ShadowEventLoop` as its `work_loader`;
- a production SHADOW service process (`src/execution/shadow_service.py`,
  `scripts/run_shadow_service.py`) now wires the durable queue, immutable
  `ShadowWork` store, and audited no-order runtime into one supervised loop:
  a named preflight gate (`src/execution/shadow_preflight.py`) checks
  `TRADING_MODE=SHADOW`, required directories, and that any existing audit's
  dataset/code/config fingerprints match the configured session before the
  process attempts to resume; real SIGTERM/SIGINT handling reuses the
  existing `GracefulShutdown` primitive; resume vs. fresh-initialize is
  chosen automatically from persisted risk state; and the process returns
  one of three explicit exit codes (0 clean, 2 preflight failed, 3 fatal
  loop error) rather than an ambiguous crash. It imports no execution
  adapter anywhere in its dependency graph. Deployment is isolated and
  disabled by default: a `shadow-service` Compose entry behind
  `profiles: ["shadow"]`, sharing no volume, container, or restart boundary
  with the active Phase 1 Bybit soak;
- a versioned Directional-to-SHADOW orchestrator now accepts one immutable
  point-in-time snapshot containing the six-family evidence request,
  portfolio state, research approval, session fingerprints, equity, and
  production time. It evaluates Directional and Meta engines before writing
  immutable `ShadowWork`; context mismatch, future evidence, unsupported
  schema, invalid clocks, or an end-to-end production lag beyond the
  configured freshness limit fails before enqueue. Promotion or research
  rejection remains a durable `WAIT`. This is a no-order bridge and imports
  no execution adapter;
- durable PAPER order/fill/position reconciliation
  (`src/execution/paper_reconciliation.py`) now backs every simulated order
  with a SQLite WAL, `synchronous=FULL` state machine: an order is durably
  recorded (`PENDING_SUBMIT`) with a deterministic, idempotent
  `client_order_id` derived from a caller-supplied idempotency key *before*
  it is ever submitted, so a retry after a crash maps onto the same order
  instead of risking a duplicate. `mark_submitted` writes ahead of the
  actual adapter call; any order still `SUBMITTED` after a restart is, by
  definition, ambiguous and is resolved only by an explicit
  `reconcile_ambiguous_order(s)` pass against an injected query function,
  never guessed. Partial fills accumulate toward a weighted average price
  and the full fee/spread/slippage/funding decomposition with overfill
  rejected as illegal; a weighted-average-cost position ledger is updated
  transactionally alongside every applied fill (open/add/partial-close/
  full-close/flip all covered). Multi-leg setups share a `leg_group_id`;
  `leg_group_status` reports `ORPHANED` when some legs carry fill exposure
  while others were rejected or remain unresolved, rather than leaving that
  state implicit;
- a strict Bybit Demo-only gateway and operator workflow now bridge one
  bounded, risk-approved `PortfolioEntryProposal` into that durable PAPER
  ledger. The gateway is non-configurably pinned to `api-demo.bybit.com`,
  consumes no mainnet credentials, verifies exact Contract Order/Position plus
  only Bybit's mandatory Unified trade bundles, rejects any asset/wallet/
  transfer permission, requires an IP restriction, and supports only linear
  Limit/PostOnly entries. Submission is write-ahead and deterministically
  idempotent across ambiguous network outcomes; executions are applied before
  exchange-confirmed fill/cancel/reject state, including partial-fill costs.
  A read-only preflight requires only `TRADING_MODE=PAPER`; an actual bounded
  place/cancel smoke additionally requires a separate exact Demo confirmation.
  This is infrastructure validation with virtual funds, not a promoted
  strategy and not LIVE;
- A narrower operator-only BTC Demo round-trip path now targets approximately
  100 USDT position notional at 100x and immediately closes the authoritative
  long size with a reduce-only Market SELL. It is recovery-safe, requires two
  exact confirmations, refuses pre-existing BTC exposure/open orders, and is
  complete only when both exchange and durable PAPER positions are flat. This
  validates plumbing with virtual funds; it is not a strategy, edge result, or
  LIVE promotion;
- operator evidence on 2026-08-24 confirmed the complete recovery-safe Demo
  path: one `0.001 BTC` BUY and one matching reduce-only SELL both filled,
  leverage was 100x, a real order-history/execution-feed lag was recovered
  without duplicating entry, and both exchange and durable PAPER positions
  ended at zero. This closes the bounded Demo plumbing proof only; automated
  promoted-setup observation and multi-day PAPER validation remain open;
- the autonomous Demo lifecycle now has a separate SQLite WAL state machine
  for observation, deterministic entry identity, open exposure, deterministic
  reduce-only exit identity, close, and persistent safety hold. A transactional
  UTC-day ledger fixes starting deployable capital, counts entries, accumulates
  realized PnL, persists cooldown, and activates the daily-loss/manual kill
  switch across process restarts. Exchange submission remains disconnected
  until the promoted-edge artifact and executor wiring are complete;
- `src/execution/paper_reconciliation.py` is not yet the durable order store
  of the automated Nautilus `TradingNode` path. `SessionRecorder` now retains
  every partial fill and deduplicates identical event replays, but a full
  crash-safe client-order-id/reconciliation bridge for that separate path
  remains future work;
- a champion/challenger drift monitor (`src/research/degradation.py`) now
  evaluates a promoted candidate's live SHADOW/PAPER behavior continuously
  against the *same* preregistered tolerances `PromotionRegistry.
  promote_to_champion` already gates on at promotion time
  (`PaperPromotionConfig.max_signal_frequency_deviation_pct`/
  `max_fill_slippage_bps`/`min_fill_rate_pct`,
  `RetirementConfig.max_paper_drawdown_pct`) - no new thresholds are
  invented. Five dimensions are checked every evaluation: data drift
  (dataset fingerprint match + freshness), signal drift (frequency
  deviation), two execution-drift checks (fill rate, slippage), and
  drawdown; missing or stale evidence is DEGRADED, never skipped
  (fail-closed, per section 2). A DEGRADED verdict is the "automatic
  transition to WAIT": it activates the existing SHADOW safety hold
  (`ShadowRuntime.activate_safety_hold`, idempotent per evaluation) - which
  already forces every subsequent Meta decision to `RISK_REJECTED`
  regardless of its action, so there is no separate WAIT state to set - and
  feeds the existing `PromotionRegistry.mark_degraded`/auto-retire-after-N
  path without duplicating that logic. Nothing in this module can promote a
  candidate. A dashboard publisher mirrors `ShadowHealthPublisher`'s atomic
  JSON + Prometheus-textfile pattern (`greenfield_degradation_verdict`,
  `greenfield_degradation_metric_within_tolerance`,
  `greenfield_degradation_dashboard_published_timestamp_seconds`), so it
  reaches the existing Grafana/Prometheus stack with no new infrastructure;
  two new Alertmanager rules (`GreenfieldCandidateDegraded`,
  `GreenfieldCandidateDashboardStale`) route through the existing
  alert-receiver pipeline. Not yet wired: an operational research-baseline
  source and a scheduled evaluation loop calling this module against real
  SHADOW/PAPER observations remain TARGET STATE.

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

1. Complete the measured raw-collector soak and restart/reboot/backlog/restore
   drills; publish data-quality and storage evidence.
2. Operationalize Binance/OKX/Coinbase/Deribit collection one venue at a time,
   each behind its own start gate, replay tests and soak evidence.
3. Build versioned feature-store jobs over trustworthy Bronze/Silver data and
   empirically validate ATAS-like and MC-like evidence without tuning on the
   same sample.
4. Run Experiment Factory OOS/walk-forward/Monte-Carlo/multiple-testing gates,
   then accumulate multi-week SHADOW/PAPER evidence before any separately
   authorized `LIVE_SMALL` discussion.

Historical operational evidence from 2026-08-25 proved the audited Demo
transport and recovery path with a flat-account boundary. The experimental
scalper that produced that evidence was retired on 2026-08-26 because it had
not passed the research/promotion gates. No continuous Demo strategy is now
part of the executable system.

The next engineering milestone is not another signal. It is a trustworthy,
replayable, observable, 24/7 raw market dataset.

Completed later on 2026-08-25: the controlled Demo lag/partial-exit fault gate
qualified with flat-account boundaries, and the bounded historical REST
backfill completed all 60 jobs. Its immutable rerun coverage report is
`qualified=true` with 57 `FULL`, three provider-bounded Bybit SOL `PARTIAL`,
zero `MISSING`, gaps, duplicates or errors. Candles remain explicitly distinct
from unavailable historical tick/L2 data. The retired Demo ATAS/MC journal
remains historical evidence only; it is not a running workload and cannot
qualify or promote a strategy.

CURRENT STATE ADDENDUM: a closed-day, fail-closed Silver-to-Gold production
job now materializes real normalized trade tape into versioned CVD/delta and
ATAS-like footprint/imbalance/POC/VAH/VAL partitions. Exact Silver content and
eligible-row lineage define the dataset version, feature code is pinned
separately, Gold output is immutable/checksummed, and every run has an
immutable report. This completes the first production Gold slice; continuous
L2, interaction, derivatives and MC-like bar feature jobs still remain before
the full feature-store phase can be accepted.

OPERATIONAL EVIDENCE (2026-08-25): an isolated full-day Bybit BTC proof read
1,051,280 checksummed Bronze events, produced 3,581,730 Silver rows and then
2,880 point-in-time Gold minute rows across the two feature sets. All four
Gold manifests independently verify, the job used 1.7 GB peak memory with no
swap, and its report SHA-256 is
`42e9bd84ab05a5ef5551f781f0fac66fa8f256041cfb46ae68fb51ba10f2cce1`.
The proof wrote outside the formal Phase 1 volume and did not restart or
modify the seven-day collector session. This proves the first production
slice on real data; it does not complete the remaining Phase 2 feature jobs.

CURRENT STATE ADDENDUM: a separate closed-day historical-bar job now writes
the original Market-Cipher-like momentum/money-flow/RSI and causally confirmed
divergence family to immutable Gold. Candle-open timestamps are shifted to
their true close-time availability, a complete day and fixed warmup are
mandatory, and future monthly appends cannot change the past dataset identity.
This family remains a veto/filter rather than another independent confirmation.

CURRENT STATE ADDENDUM: daily microstructure Gold now also has a dedicated,
chunk-stable interaction feature set for sweeps, absorption, exhaustion and
price progress. Previous-bucket state survives Silver part boundaries, while
strict stream ordering and symbol/type contracts fail closed. These related
fields remain one order-flow interaction family, not multiple confirmations.

CURRENT STATE ADDENDUM: a production closed-day L2 Silver-to-Gold job now
warm-starts from the last pre-day snapshot and emits causal minute aggregates
for spread, depth, microprice, book imbalance, additions, cancellations and
replenishment. State is connection-scoped; reconnect without a fresh snapshot,
sequence gaps, corrupt parts and accumulator misalignment fail closed. The job
and immutable report are tested, while a real full-day proof remains pending
until the current collector has completed its first whole UTC day.

CURRENT STATE ADDENDUM: exact Gold dataset/code tuples can now be audited into
an immutable empirical distribution report. Every source manifest and Parquet
checksum is reverified before descriptive statistics are computed; mixed
schemas, duplicate timestamps, non-finite values and corrupt parts fail closed.
This is feature-data QA only and must not be presented as edge validation or a
promotion gate.

OPERATIONAL EVIDENCE: the full-day Bybit BTC microstructure rebuild now
produces all three production slices — trade flow, footprint auction and ATAS-
like trade interaction — totaling 4,320 causal minute rows. All six manifests
independently verify. Separate immutable distribution audits also verified
these three sets and the 1,440-row Market-Cipher-like set. The only constant
columns are two explicit configuration parameters, not directional signals.

OPERATIONAL EVIDENCE: a real Bybit BTCUSDT 1-minute build for 2026-08-24
produced all 1,440 causal Gold rows from a complete day plus 256 warmup bars.
Both availability-date manifests verify and an immediate rerun was
idempotent. Dataset version is
`9b6181d33c3b53ee50eab14d056d97f50f2313fbfc349d78002607119a4794c8`;
report SHA-256 is
`dc32edfac702428635addccbd60f76d98c01a971884a0ab8f92e873946e83e34`.

## 22. Bybit Demo execution skeleton status (2026-08-26)

CURRENT STATE: both experimental continuous strategies have been retired from
the executable codebase. The ATAS/MC v1 candidate had no promoted edge; the
liquidation-fade v2 candidate had only 27 coarse-screen trades and was negative
after configured fees. Their runners, scanners, strategy-specific feeds,
validation journals, backtest wrapper, force-once mechanism and both Compose
profiles are removed. No autonomous Demo strategy is running or startable from
the repository.

The proven Bybit Demo transport and safety skeleton remains: authenticated
preflight, balance/exposure inspection, deterministic client-order identity,
order/fill reconciliation, partial-fill and restart recovery, durable lifecycle
and daily risk state, one-position guard, reduce-only exits, health publisher,
flat-account recovery drill and an explicitly confirmed bounded BTC round-trip
infrastructure test. `DemoStrategyExecutor` is a library only: it has no signal
adapter, no background runner and requires an explicit risk configuration.

TARGET STATE: when Experiment Factory finds a candidate that passes the
preregistered OOS, walk-forward, adverse-cost, DSR/PBO, parameter-stability and
confirmation-independence gates, add one versioned adapter that maps its
immutable evidence to LONG/SHORT/WAIT, explicitly configures Demo risk and
binds the existing skeleton. The new service must be disabled by default,
Demo-endpoint pinned, content-address the qualification artifact, pass recovery
drills and remain separate from LIVE. Historical v1/v2 code must not be revived
or copied into the new adapter merely to create activity.

## 23. Safety-remediation checkpoint (2026-08-25)

CURRENT STATE: every reproducible item supplied in the August repository audit
has a code fix and regression coverage: monotonic daily-loss ledgers,
non-bypassable multi-family independence promotion, fail-closed non-finite
correlation, restart-safe residual Demo exits, execution-feed lag retry,
immutable daily baseline with variable current equity, healthy insufficient-
data WAIT, complete partial-fill session recording, entry-risk release on
rejection, Decimal tick binning, corrupt-directory compaction isolation, and
exact experiment execution metadata. The full local suite passes with 1585
tests and 3 intentional skips.

HISTORICAL OPERATIONAL ADDENDUM: commits through `f2e59d2` proved that history
and Bronze inputs could share the dedicated data mount, recent-manifest queries
were bounded, a real hybrid BTC scan completed, and the Demo account remained
flat. The experimental scalper referenced by that checkpoint was removed on
2026-08-26 and is no longer a workload. BTC/ETH/SOL raw collection evidence is
independent of that retired strategy and must be assessed by the Phase 1 soak
criteria. The exact CI contract (`ruff`, `mypy src scripts`, coverage tests,
secret scan, monitoring configuration and container builds) was green at that
historical checkpoint.

SOAK AUDIT ADDENDUM: the session started on 2026-08-22 is retained as useful
raw data but is not Phase 1 acceptance evidence. A machine audit observed only
about 70 hours and a maximum heartbeat gap of about 510 seconds, above the
30-second limit. The next qualified attempt must start from a dedicated clean,
commit-pinned checkout, preserve existing Bronze, and produce a fresh preflight
and capacity forecast against current free space.

TARGET STATE still not satisfied: a green local suite is not multi-day market
evidence. Phase 1 needs operational soak/recovery evidence; Phase 3 needs
production transports and soaks across all target exchanges; Phase 4/5 needs
enough proprietary Bronze history to validate order-flow/options features;
Phase 8 Neutral/Arbitrage remains research-only; Phase 9 needs multi-week
SHADOW/PAPER promotion evidence; Phase 10 remains forbidden until a separate
human authorization. The non-summarized remainder of the external "22 finding"
report must be supplied before it can be claimed as independently closed.

## 24. Completion checkpoint (2026-08-25)

This checkpoint separates implemented code from operational acceptance. A
feature is not counted as production-complete merely because unit tests pass.

- Phase 0 is complete and reproducible.
- Phase 1 is running a clean, commit-pinned seven-day Bybit BTC/ETH/SOL soak;
  elapsed time and the required reboot/backlog/restore drills are still gates.
- Phase 2 contracts and the main Bronze/Silver/Gold paths are implemented;
  scheduled quality/catalog operation and backup restore proof remain.
- Phase 3 adapters, replay gates and collector implementations exist for all
  target venues, but continuous live Binance/OKX/Coinbase/Deribit deployment
  and soak evidence remain.
- Phase 4 has production trade-flow, footprint, interaction, MC-like and L2
  materializers plus immutable empirical distribution QA. Real L2 full-day
  evidence, longer proprietary coverage and fill-feasibility calibration
  remain.
- Phases 5-8 have substantial typed feature/engine foundations, but still need
  production multi-venue inputs, materialization and empirical research gates.
- Phase 9 has SHADOW/PAPER/Demo execution and recovery infrastructure, but no
  candidate has passed the required multi-week promoted observation gates.
- Phase 10 LIVE_SMALL remains intentionally disabled and separately
  authorized. Phase 11 advanced macro/on-chain/ETF/CME and justified AI remain
  later work.

Planning estimate (not an acceptance claim): about 72% of the intended code
surface exists, while roughly 60% of the complete MASTER PLAN is satisfied
when mandatory runtime evidence is included. Approximately 40% therefore
remains, dominated by elapsed soaks, multi-exchange production operation,
empirical edge validation, SHADOW/PAPER time and advanced context—not by adding
more unvalidated indicators.

## 25. ATAS historical-data bridge

TARGET STATE: investigate ATAS as an additional, explicitly external source of
historical crypto microstructure rather than assuming that all historical tick
and depth data are unavailable. The ATAS indicator API documents bounded
historical cumulative-trade requests and historical market-depth snapshot
requests; actual retention and full-depth availability remain connector- and
provider-dependent and therefore require an empirical Bybit test.

The next work session must:

1. build a minimal Windows/.NET ATAS custom-indicator export probe;
2. query the Bybit BTCUSDT connector for its reported cumulative-trade history
   depth and request one old day without volume filtering;
3. request the same day's historical DOM/depth data and prove whether it is
   real exchange depth or generated/limited depth;
4. record the earliest available date, request/session limits, row counts,
   timestamps, depth levels, gaps and connector identity for BTC, then repeat
   only after BTC is understood for ETH and SOL;
5. compare one overlapping day against Greenfield's native Bybit Bronze archive
   before accepting the source;
6. import accepted exports through a separate immutable `source=atas` Bronze
   path with checksums, manifests and point-in-time lineage—never merge them
   silently with native exchange capture;
7. review ATAS/data-provider licensing and redistribution terms before any
   automated bulk archive.

This investigation does not weaken the native 24/7 collectors or the Phase 1
soak. ATAS-derived data cannot be called complete L2 history until the connector
passes the overlap, continuity and provenance checks above. The ATAS desktop/API
requires a Windows host; the current Ubuntu VPS remains the Greenfield storage,
validation and research host rather than the ATAS runtime.

### CURRENT STATE — first bridge implementation

- The official-API C# probe source now exists under `integrations/atas/`. Its
  first bounded capability is an unfiltered cumulative-trade request of at
  most seven days with explicit connector/instrument/time identity, completion
  footer and SHA-256 sidecar. It creates no strategy signal.
- `scripts/ingest_atas_history_export.py` validates JSONL structure, UTC,
  monotonic timestamps, decimal strings, counts, completeness, request bounds,
  optional DOM ordering/crossing and an operator-supplied checksum. Accepted
  bytes land content-addressed under `bronze/source=atas/...` with an immutable
  manifest; they are never relabelled as native Bybit capture.
- The workstation contains old `%APPDATA%\\ATAS` cache/config data but no
  discoverable installed ATAS application/SDK and no .NET SDK. Consequently
  the source and Greenfield ingest boundary are testable now, but a compiled
  DLL, connector response and retention-depth claim are **not** complete.
- Historical DOM remains unclaimed. The landing schema validates such records,
  but the exporter must only add them after an installed Bybit connector proves
  `GetMarketDepthSnapshotsAsync` returns genuine provider history.

### TARGET STATE — remaining bridge acceptance

Install/locate ATAS plus its matching .NET SDK on Windows, compile/load the
probe, export one old BTC day, record provider limits and then implement/test
historical depth. Compare an overlapping BTC day against native Bronze for
coverage, timing and continuity before extending to ETH/SOL or bulk day-by-day
exports. Licensing review remains a hard prerequisite for bulk retention or
redistribution.

### CURRENT STATE — retired Demo candidates and preserved safety boundary

The ATAS/MC v1 and liquidation-fade v2 candidates are removed from executable
code. V2's five-day sample had only 27 trades and became slightly negative
after configured fees; a minimum startup gate could not turn that into proven
edge. The strategy-specific gate was therefore removed together with the
candidate instead of being mistaken for promotion evidence. Research Factory
OOS, walk-forward, adverse-cost, anti-overfitting, confirmation-independence
and human promotion gates remain mandatory for any future candidate.
