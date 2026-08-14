# Backtesting

## Engine

[NautilusTrader](https://nautilustrader.io) is the backtest/paper/(eventually)
live execution engine — see `docs/PHASE_0_ARCHITECTURE_RESEARCH.md` section 2
and 4 for the full comparison against Freqtrade, VectorBT, and Backtrader.
The same strategy code runs in backtest, paper, and live, which removes the
risk of backtest results not matching real behavior.

VectorBT is used *inside* the backtest/analytics layer for fast exploratory
parameter sweeps and Monte Carlo before committing to a full, realistic
NautilusTrader run — it is not a second execution engine.

## Realism requirements

A backtest is not accepted if it assumes perfect execution at the close
price. Every run must account for, and record as part of its experiment
metadata:

- fees
- spread
- slippage
- leverage
- liquidation risk
- funding
- position sizing
- stop-loss / take-profit behavior

## Lookahead / leakage protection

- Features may only use information available up to time `t`.
- No random `train_test_split` — time-series split, purged split, or
  walk-forward only (see `docs/RESEARCH_METHODOLOGY.md` and `docs/ML.md`).
- `tests/lookahead/` exists specifically to catch a feature or strategy that
  "sees the future" (e.g. by truncating a dataset at different points and
  asserting a feature's historical values don't change).
- Survivorship bias: the symbol universe used in any historical backtest
  must reflect what was actually tradeable at that time, not today's list.

## Benchmarks

Every strategy is compared against Buy & Hold, Random Entry, Simple Trend
Following, and Simple Mean Reversion, run through the same pipeline (same
costs, same risk engine) — see `docs/RESEARCH_METHODOLOGY.md`.

## Walk-forward

Automated sliding-window framework (e.g. TRAIN 12mo / VALIDATION 3mo / TEST
3mo). The reported equity curve is composed from consecutive TEST windows
only. Designed in Phase 7.

## Funding (approximation)

The installed NautilusTrader version has no built-in perpetual-funding
simulation module, and Bybit's funding rate history isn't fully available
either (`docs/DATA.md`). Rather than fabricate in-engine funding mechanics
against assumptions we can't verify, `src/backtesting/funding.py` computes
funding as an explicit **post-hoc cost adjustment**: given a position's open/
close time and average entry price, it counts how many of Bybit's standard
funding settlements (00:00/08:00/16:00 UTC) the position was held through
and multiplies by a configurable `rate_per_interval`. This is deliberately
visible and swappable rather than silently baked into the simulated PnL —
see open research question 2 in `docs/PROJECT_STATUS.md`.

## Implementation (Phase 3)

- `src/backtesting/instruments.py` — builds NautilusTrader `CryptoPerpetual`
  instruments from `configs/instruments.yaml`. **That config file's specs
  (tick size, lot size) are uniform placeholders, not a live sync from
  Bybit's instrument-info endpoint** — the fee schedule (maker/taker) is a
  commonly documented default and should hold reasonably well, but
  precision/increment values need a live sync before being trusted for
  anything beyond validating the engine's plumbing (same network limitation
  as Phase 2 — see `docs/PROJECT_STATUS.md`).
- `src/backtesting/data_adapter.py` — converts a canonical klines DataFrame
  (`src/data/schema.py`) into NautilusTrader `Bar` objects via
  `BarDataWrangler`.
- `src/backtesting/costs.py` — `ExecutionAssumptions`: a `MakerTakerFeeModel`
  (reads each instrument's own maker/taker fee) and a `FillModel` with
  configurable, reproducible (seeded) one-tick slippage probability.
- `src/backtesting/funding.py` — the funding approximation described above.
- `src/backtesting/engine.py` — `build_engine`/`run_backtest`: assembles a
  `BacktestEngine` with the Bybit venue (margin account, configurable
  default leverage), instruments, bar data from `src/data/storage`, and the
  cost models above. Runs with **zero strategies attached** — this proves
  the full data → instrument → venue → cost pipeline end to end without
  requiring any strategy family, which is a Phase 5+ concern.
- `scripts/run_backtest.py` — CLI entry point exercising the above against
  locally stored Parquet data.

This document defines the target backtesting approach; strategy families
(Buy & Hold, Random Entry, Trend Following, Mean Reversion) are implemented
in Phase 5 on top of this engine — see `docs/PROJECT_STATUS.md`.
