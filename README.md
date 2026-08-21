# Greenfield Market Intelligence

Greenfield is a research, market-intelligence, and controlled-execution
platform for BTC, ETH, and SOL. Its purpose is to determine whether a
hypothesis has a real, stable, executable edge — not to maximize an in-sample
backtest.

The authoritative scope, architecture, phase order, safety rules, and
Definition of Done are in
[docs/GREENFIELD_V2_MASTER_PLAN.md](docs/GREENFIELD_V2_MASTER_PLAN.md).

## Current state

The repository already contains a substantial v1 core:

- Bybit OHLCV, funding, open-interest, long/short-ratio, trade, order-book, and
  liquidation data collection;
- Parquet storage, integrity checks, microstructure parsing, and compaction;
- NautilusTrader backtests with fees, slippage, funding, entry-delay stress,
  mark-to-market handling, and walk-forward evaluation;
- Monte Carlo, bootstrap, Deflated Sharpe Ratio, Probability of Backtest
  Overfitting, parameter-stability, and portfolio analytics;
- an Experiment Factory with hypothesis, queue, orchestrator, evaluator,
  promotion, ledger, locking, and reporting components;
- benchmark and research strategy families;
- causal market-regime and feature pipelines;
- risk, paper execution, fill tracking, heartbeat, session checkpointing, and
  supervision;
- Docker Compose services for research, paper, collectors, and compaction.

Real LIVE order submission remains intentionally disabled.

## Greenfield v2 target

The v2 program extends the core with:

- lossless, replayable raw market collection running 24/7;
- Bybit, Binance, OKX, Coinbase, and Deribit;
- tick, trades, L2/DOM, footprint, delta, CVD, imbalance, absorption,
  exhaustion, sweeps, Volume Profile, POC, VAH/VAL, VWAP, and AVWAP;
- an independently implemented Market Cipher-like momentum, money-flow, and
  divergence family using public mathematical concepts only;
- derivatives, options, cross-market, regime, and historical-analog layers;
- Directional, Neutral/Arbitrage, Research, and Meta Engines;
- LONG, SHORT, WAIT, and ARBITRAGE setup contracts;
- shadow, paper, and gated LIVE_SMALL promotion.

The immediate engineering priority is the raw collector and owned
microstructure dataset, not more strategies or AI.

## Supported environment

The reproducible core is deliberately pinned to:

- CPython 3.11.x; CI and Docker use 3.11.15;
- uv 0.12.1 for locked dependency installation;
- NautilusTrader 1.221.0.

Python 3.12 is not currently supported because NautilusTrader 1.231 changed
the Bybit and fill-model APIs used by this core. Support may be reconsidered
through a dedicated compatibility change with full tests.

## Getting started

Install uv, then from the repository root:

    uv sync --all-extras --locked
    uv run ruff check .
    uv run mypy src
    uv run pytest -q

The lockfile is mandatory. Do not replace the locked install with an
unconstrained pip install.

Docker:

    copy .env.example .env
    docker compose build
    docker compose run --rm tests

On Linux or macOS, use cp instead of copy.

See [docs/MAINTAINER_RUNBOOK.md](docs/MAINTAINER_RUNBOOK.md) for the clean
checkout, branch, validation, recovery, and release workflow.

## Runtime modes

- RESEARCH — data, analysis, and bounded Experiment Factory work;
- BACKTEST — historical simulation and robustness evaluation;
- PAPER — approved paper candidates only;
- LIVE — denied by the current execution implementation.

An automated research worker may propose and test hypotheses. It cannot
approve a paper champion, enable LIVE, or allocate real capital.

## Repository layout

- src/data — clients, collectors, schemas, storage, validation;
- src/features — causal point-in-time features;
- src/strategies — benchmark and research strategies;
- src/regimes — regime indicators, classification, and analysis;
- src/backtesting — engine, costs, funding, runner, walk-forward;
- src/analytics — metrics, robustness, Monte Carlo, reports;
- src/research — Experiment Factory;
- src/risk and src/portfolio — risk decisions and exposure aggregation;
- src/execution — paper adapters, tracking, supervision, preflight;
- src/ml — baselines, splits, evaluation, calibration, model artifacts;
- configs — universe, instruments, and research protocol;
- scripts — command-line entry points;
- tests — unit, integration, lookahead, and data-integrity coverage;
- docs — architecture, methodology, operations, and the master plan.

## Branch model

- main — legacy default branch; not yet promoted to the full application;
- codex/stable-greenfield-v1-core — preserved selected core;
- codex/greenfield-market-intelligence-v2 — v2 integration branch;
- codex/phase-* or other short-lived branches — reviewed implementation work;
- claude/* — retained historical branches; never rewritten or deleted.

Changes enter the integration branch through pull requests. Execution, risk,
credentials, and promotion-gate changes require explicit human review.

## Core safety rules

- WAIT is a valid and frequent decision.
- Correlated price indicators do not count as independent confirmations.
- Fees, spread, slippage, latency, partial fills, funding, and operational
  failure belong in validation.
- OOS, walk-forward, multiple-testing, and parameter-stability controls are
  mandatory.
- No real-money LIVE path or capital increase is enabled without separate,
  explicit human authorization.
- Secrets, raw market archives, models, and generated reports are not
  committed.

## Documentation

- [Master plan](docs/GREENFIELD_V2_MASTER_PLAN.md)
- [Maintainer runbook](docs/MAINTAINER_RUNBOOK.md)
- [Architecture](docs/ARCHITECTURE.md)
- [Research methodology](docs/RESEARCH_METHODOLOGY.md)
- [Data](docs/DATA.md)
- [Backtesting](docs/BACKTESTING.md)
- [VPS deployment](docs/VPS_DEPLOYMENT.md)
- [Historical project status](docs/PROJECT_STATUS.md)
