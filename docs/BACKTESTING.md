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

## Status

This document defines the target backtesting approach. The NautilusTrader
integration and benchmark strategies are implemented in Phases 3 and 5 — see
`docs/PROJECT_STATUS.md`.
