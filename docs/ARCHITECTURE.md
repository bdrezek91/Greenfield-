# Architecture

This document describes the system architecture chosen in Phase 0
(`docs/PHASE_0_ARCHITECTURE_RESEARCH.md`) and how the repository implements it.
Read that document first for the full comparison and rationale — this page is
the living reference for "how the layers actually fit together" as the code
grows.

## Layered design

```
DATA -> FEATURES -> STRATEGY/SIGNAL -> BACKTEST ENGINE -> RISK ENGINE
     -> PORTFOLIO ENGINE -> EXECUTION -> ANALYTICS -> ML/AI
```

Each layer lives in its own package under `src/` and communicates with its
neighbors through plain data (pandas DataFrames / Parquet), not through
shared mutable state or cross-layer imports of internal details.

| Layer | Package | Owns |
|---|---|---|
| Data | `src/data` | Ingestion from Kraken Futures, validation, Parquet storage |
| Features | `src/features` | Point-in-time feature computation (no lookahead) |
| Strategy | `src/strategies` | Signal generation per strategy family |
| Regimes | `src/regimes` | Market regime classification |
| Backtest | `src/backtesting` | NautilusTrader integration, VectorBT exploration |
| Risk | `src/risk` | Position sizing, risk limits |
| Portfolio | `src/portfolio` | Multi-instrument aggregation, correlation, exposure |
| Execution | `src/execution` | Order intent -> exchange adapter (backtest/paper/live) |
| Analytics | `src/analytics` | Experiment tracking, metrics, Monte Carlo, robustness |
| ML | `src/ml` | Baseline models, regime classifiers, calibration, explainability |

## Boundary rule

`src/backtesting` and `src/execution` are the **only** packages allowed to
import `nautilus_trader` (or, inside `backtesting`, `vectorbt`) directly.
Every other package operates on plain DataFrames/Parquet. This is what keeps
the execution engine swappable in theory and, more importantly, keeps
`features`, `strategies`, `risk`, `ml`, and `analytics` testable in isolation
without spinning up a full backtest engine.

## Why NautilusTrader over Freqtrade/Backtrader/custom

Summarized from Phase 0 (full reasoning in
`docs/PHASE_0_ARCHITECTURE_RESEARCH.md`, section 4):

- Same engine and same strategy code for backtest, paper, and (eventually)
  live — removes the backtest-vs-live drift class of bugs.
- Realistic fill/fee/slippage/funding/leverage/margin model, closer to actual
  exchange behavior than vectorized engines.
- Naturally enforces the layering above; VectorBT is used *inside* the
  analytics/backtest layer for fast exploratory parameter sweeps and
  Monte Carlo, not as a replacement for the execution engine.

## Runtime modes

`RESEARCH`, `BACKTEST`, `PAPER` are available from the start. `LIVE` is
disabled by default and requires an explicit, separately implemented safety
flag introduced in a later phase — it must never be reachable by accident.

## Status

As of Phase 1, this repository contains the directory/package skeleton,
Docker/CI infrastructure, and documentation only. No data ingestion,
strategy, backtest, risk, or ML logic has been implemented yet — see
`docs/PROJECT_STATUS.md` for the current phase and what's next.
