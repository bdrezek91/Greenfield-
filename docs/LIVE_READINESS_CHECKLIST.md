# LIVE Readiness Checklist

Phase 15 of this project. Read this before even considering setting
`TRADING_MODE=LIVE`.

## What actually exists right now

**No script in this repository ever submits a live order.**
`src/execution/kraken_adapter.py:KrakenExecutionAdapter` can technically be
constructed with `TradingMode.LIVE` (it has to - PAPER and LIVE differ only
in which Kraken environment `ccxt` points at, demo vs. production), but
every actual entry point (`scripts/paper_trade.py`,
`scripts/run_paper_session.py`) hard-requires `TRADING_MODE=PAPER` and
refuses anything else before running. There is deliberately no
`scripts/live_trade.py`. `scripts/live_preflight_check.py`
(`src/execution/live_preflight.py`) checks whether the *conditions* for
going live are met - it does not, and cannot, start live trading, because
no entry point that would do so exists yet.

This document and the preflight gate are infrastructure for **when** that
path is eventually built - deliberately kept separate from building it, so
that decision gets made explicitly, by a human, and not as an incidental
side effect of "preparing."

## Two independent gates, both required

1. **`CONFIRM_LIVE_TRADING` env var gate** (`src/execution/mode.py`,
   Phase 10) - `TRADING_MODE=LIVE` alone is refused; also requires
   `CONFIRM_LIVE_TRADING=I_UNDERSTAND_THE_RISK` set explicitly.
2. **Preflight readiness gate** (`src/execution/live_preflight.py`, this
   phase) - even with both of the above set, checks: API credentials are
   present, intended risk parameters are within conservative bounds (catches
   e.g. `src.strategies.base.BenchmarkStrategyConfig`'s backtest-oriented
   defaults - `risk_per_trade=0.1`, `max_leverage=10.0` - which are fine
   for a sandboxed backtest and reckless for real capital), and at least
   one experiment has actually been recorded (evidence of testing, not
   evidence of a good strategy).

Run it:

```bash
python scripts/live_preflight_check.py \
    --risk-per-trade 0.01 --max-portfolio-risk 0.05 \
    --max-daily-loss 0.03 --max-drawdown 0.2 --max-leverage 3.0
```

Both gates passing is necessary. Neither is sufficient - the manual
checklist below covers everything a program can't verify about itself.

## Manual checklist (not automatable, sign off explicitly)

- [ ] **Strategy validated out-of-sample.** Backtested, walk-forward
  tested (`src/backtesting/walk_forward.py`), and beats the mandatory
  Random Entry benchmark with statistical significance accounted for
  (Deflated Sharpe Ratio, PBO - `docs/RESEARCH_METHODOLOGY.md`) - not just
  "looks good on one backtest run."
- [ ] **Paper-traded for a meaningful period** (`scripts/
  run_paper_session.py`, Phase 14) against Kraken's demo-futures
  environment, with the section-32 expected-vs-actual fill comparison
  reviewed - not just constructed successfully, actually run and its
  `FillTracker` summary read by a human.
- [ ] **Real Kraken demo-environment connectivity verified end to end** on
  the target VPS/machine - every "NOT VERIFIED IN THIS SESSION" note in
  this codebase (`src/execution/kraken_adapter.py`,
  `docs/PROJECT_STATUS.md`, this file) traces back to this same sandbox's
  blocked network egress to `kraken.com`. Confirm this actually works
  before anything past it matters.
- [ ] **Capital allocation decided and bounded**, in writing, by whoever
  owns that decision - never inferred from code defaults. Confirm the
  actual USDT amount at risk, and that it's capital the owner can afford
  to lose entirely.
- [ ] **Kill switch procedure defined and tested**: the fastest path to
  flatten all positions and stop new order submission (not just stopping
  the process - open positions on the exchange survive a process kill).
  Know this command/procedure before you need it, not while reacting to a
  loss.
- [ ] **Monitoring and alerting wired up**: something outside the trading
  process itself (uptime check, log-based alert, exchange notification)
  that fires if the process dies, the risk engine's daily-loss/drawdown
  limits are hit, or the connection drops silently
  (`src/execution/heartbeat.py`, Phase 14, is a building block here - not
  yet wired to an actual alert channel).
- [ ] **Incident response plan written down**: who gets paged, what the
  first three actions are, where logs/state
  (`src/execution/session_state.py` checkpoints) are found during an
  incident - decided calmly in advance, not improvised during one.
- [ ] **Rollback plan**: how to go from LIVE back to PAPER/BACKTEST if
  something looks wrong, including what happens to any open live position
  while doing so.
- [ ] **Production API keys are actually production keys**, scoped to
  trading only (no withdrawal permission), stored per `.env`'s existing
  rules (never committed, never logged) - and are NOT the same keys used
  for `PAPER` (which must be keys generated on `demo-futures.kraken.com`,
  a separate account from the real one, per `.env.example`).

## Why this is this cautious

Per the project's own founding rules (`docs/PHASE_0_ARCHITECTURE_RESEARCH.md`,
`docs/RESEARCH_METHODOLOGY.md`): only RESEARCH/BACKTEST/PAPER are allowed
by default, LIVE is blocked, and trading decisions must be deterministic
and auditable - never rushed. A phase named "LIVE preparation" building
the actual live order-submission path in the same breath as its own safety
gate would defeat the purpose of having a gate. That path is a distinct,
future decision.
