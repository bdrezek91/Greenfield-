# VPS Deployment

## Target environment

Linux VPS, Docker + Docker Compose, Git/GitHub as the source of truth. No
Windows-specific assumptions anywhere in the codebase or tooling.

## Getting started

```bash
git clone <repo-url>
cd ai-trading-lab
cp .env.example .env   # fill in real values, .env is gitignored
docker compose build
docker compose up -d research
```

Run the test suite in a container (matches CI):

```bash
docker compose run --rm tests
```

## Services

`docker-compose.yml` defines logically separate services rather than a
single monolithic container. As of Phase 1:

- `research` — long-running interactive workspace for backtests/experiments.
- `tests` — one-shot test runner.

Additional services (`data-collector`, `execution`, `monitoring`) are added
in later phases once they have real code behind them, following the same
principle: each service does one job and can be restarted/scaled
independently.

## Secrets

API keys and other secrets are provided exclusively through `.env`
(gitignored). `.env.example` documents every required variable with no real
values. No secret is ever hardcoded or committed.

## Runtime modes

`TRADING_MODE` in `.env` controls `RESEARCH` / `BACKTEST` / `PAPER` / `LIVE`,
enforced by `src/execution/mode.py:resolve_trading_mode()` (Phase 10) —
every entry point that might submit real orders routes through it rather
than reading `TRADING_MODE` directly. `LIVE` is refused unless the
environment variable `CONFIRM_LIVE_TRADING=I_UNDERSTAND_THE_RISK` is *also*
set explicitly — not reachable by setting `TRADING_MODE=LIVE` alone. No
script in this repository ever constructs a live-trading run regardless
(only `PAPER`, against Kraken's demo-futures environment via
`scripts/paper_trade.py`, is implemented — see
`docs/LIVE_READINESS_CHECKLIST.md`).

## Paper trading (Kraken demo environment)

```bash
export TRADING_MODE=PAPER
export KRAKEN_API_KEY=...      # generated on demo-futures.kraken.com - never a production key here
export KRAKEN_API_SECRET=...
python scripts/paper_trade.py --symbol BTCUSD --timeframe 1h \
    --risk-per-trade 0.01 --max-portfolio-risk 0.05
```

Unlike the prior Bybit configuration, this does NOT run a NautilusTrader
`Strategy` class unchanged from backtest to paper - no released
NautilusTrader version ships a Kraken adapter (verified directly against
the installed wheel; see `docs/PROJECT_STATUS.md`'s exchange migration
entry). Instead, `src/execution/live_runner.py:LiveRunner` runs the
momentum entry rule (`src/strategies/signals.py:momentum_signal`, the same
function `src.strategies.momentum.Momentum` uses in backtests) against
this project's own `RiskEngine`/`ExecutionAdapter`/`FillTracker`
infrastructure, submitting orders through
`src/execution/kraken_adapter.py:KrakenExecutionAdapter` (via `ccxt`).
Other strategy families (breakout, mean_reversion, ...) still only run
inside NautilusTrader's `BacktestEngine` - porting them to `LiveRunner` is
a follow-up, not yet done. See `docs/RESEARCH_METHODOLOGY.md` for the
expected-vs-actual fill comparison this mode is meant to produce (latency,
slippage, rejected orders, data issues).

**Known limitation:** this repository's development sessions run under a
network policy that blocks `kraken.com`, so live demo-environment
connectivity has not been exercised end to end in that environment - the
individual pieces (`LiveRunner`'s signal/risk/exit logic,
`KrakenExecutionAdapter`'s request/response handling) are unit-tested with
injected fake transports, but no real network call has been made (see
`docs/PROJECT_STATUS.md`). Validate connectivity on the actual VPS or a
local machine with unrestricted network access before relying on this.

## Long-running paper trading (Phase 14)

`scripts/paper_trade.py`'s polling loop runs forever with no restart
logic: any failure (e.g. a demo-environment disconnect) kills the whole
process. For a session meant to run for days, use the supervised entry
point instead:

```bash
export TRADING_MODE=PAPER
export KRAKEN_API_KEY=...
export KRAKEN_API_SECRET=...
python scripts/run_paper_session.py --symbol BTCUSD --timeframe 1h \
    --checkpoint-path reports/paper_session.json
```

This adds two things on top of `paper_trade.py`:

- **Restart with backoff** (`src/execution/supervisor.py`): a failure
  triggers a retry with exponential backoff, up to `--max-restarts`,
  instead of the process dying on the first disconnect.
- **Durable checkpointing** (`src/execution/session_state.py`): restart
  count, last error, and the latest fill summary (fed by `LiveRunner`'s own
  `FillTracker`, populated directly from each `KrakenExecutionAdapter.submit()`
  call - no NautilusTrader event bridge needed on this path, unlike the
  prior Bybit configuration's `src/execution/session_recorder.py`) are
  written to `--checkpoint-path` as plain JSON before and after every
  attempt, so a full process restart (a deploy, an out-of-memory kill,
  `docker compose restart`) resumes the session's history instead of
  losing it.

Same known limitation as above: not exercised against real Kraken demo
connectivity in this repository's development sessions. The
retry/checkpoint logic is unit-tested with an injected failing `run_fn`
(`tests/unit/test_supervisor.py`), and `LiveRunner`'s full signal → risk →
execution → fill-tracking loop is unit-tested with a fake execution
adapter (`tests/unit/test_live_runner.py`) — only the live network path is
unverified here.

## Data persistence

Datasets and models live in a Docker volume / host directory
(`DATA_DIR`), never inside the git-tracked repository tree.

## Monitoring (planned)

Service health, data freshness, exchange connectivity, last candle/trade,
error rates, CPU/RAM/disk, restart counts. Designed structurally now,
implemented operationally from Phase 9 onward.

## Status

This document defines the target deployment approach. Additional services
and monitoring are added as the corresponding layers are implemented — see
`docs/PROJECT_STATUS.md`.
