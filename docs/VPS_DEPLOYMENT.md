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
live-trading execution path exists yet regardless (only `PAPER`, against a
Bybit simulation backend via `scripts/paper_trade.py`, is implemented).

## Paper trading (Bybit testnet or Demo Trading)

Two simulation backends are supported, selected with `--backend` (see
`src/execution/paper_node.py`'s module docstring):

```bash
# --backend testnet (default): requires a *separate* testnet.bybit.com
# account registration - geo-blocked for some EU users independent of a
# regular bybit.com account.
export TRADING_MODE=PAPER
export BYBIT_API_KEY=...       # Bybit TESTNET key - never a mainnet key here
export BYBIT_API_SECRET=...
python scripts/paper_trade.py --symbol BTCUSDT --timeframe 1h --strategy trend_following

# --backend demo: Bybit's "Demo Trading" feature, reachable from an
# existing regular bybit.com login (avatar menu -> Demo Trading), no
# separate site registration - use this if testnet.bybit.com registration
# is geo-blocked for you. Still fully isolated virtual funds; generate
# these keys while switched into Demo Trading mode, never your real
# mainnet keys.
export TRADING_MODE=PAPER
export BYBIT_DEMO_API_KEY=...
export BYBIT_DEMO_API_SECRET=...
python scripts/paper_trade.py --symbol BTCUSDT --timeframe 1h \
    --strategy trend_following --backend demo
```

This runs the exact same `Strategy` class used in backtests
(`src/strategies/`) live against the chosen Bybit simulation backend, via
NautilusTrader's native Bybit adapter (`src/execution/paper_node.py`) —
the Phase 0 architecture decision's payoff: no strategy code changes
between backtest and paper. See `docs/RESEARCH_METHODOLOGY.md` for the
expected-vs-actual fill comparison this mode is meant to produce (latency,
slippage, rejected orders, data issues).

**Known limitation:** this repository's development sessions run under a
network policy that blocks `api.bybit.com`, so live testnet connectivity
has not been exercised end to end in that environment (only construction of
the trading node, without connecting, has been verified — see
`docs/PROJECT_STATUS.md`). Validate connectivity on the actual VPS or a
local machine with unrestricted network access before relying on this.

## Long-running paper trading (Phase 14)

`scripts/paper_trade.py`'s `node.run()` is a single blocking call: any
failure (e.g. a testnet disconnect) kills the whole process. For a session
meant to run for days, use the supervised entry point instead:

```bash
export TRADING_MODE=PAPER
export BYBIT_API_KEY=...
export BYBIT_API_SECRET=...
python scripts/run_paper_session.py --symbol BTCUSDT --timeframe 1h \
    --strategy trend_following --checkpoint-path reports/paper_session.json
```

Also accepts `--backend demo` (with `BYBIT_DEMO_API_KEY`/`BYBIT_DEMO_API_SECRET`)
in place of the testnet env vars, same as `paper_trade.py` above.

This adds three things on top of `paper_trade.py`:

- **Fill recording** (`src/execution/session_recorder.py`): real
  `OrderFilled`/`OrderRejected` events are scored against the intents that
  produced them (the section-32 expected-vs-actual comparison
  `docs/RESEARCH_METHODOLOGY.md` calls for), not just replayed backtest
  trades.
- **Restart with backoff** (`src/execution/supervisor.py`): a failure
  triggers a retry with exponential backoff, up to `--max-restarts`,
  instead of the process dying on the first disconnect.
- **Durable checkpointing** (`src/execution/session_state.py`): restart
  count, last error, and the latest fill summary are written to
  `--checkpoint-path` as plain JSON before and after every attempt, so a
  full process restart (a deploy, an out-of-memory kill, `docker compose
  restart`) resumes the session's history instead of losing it.

Same known limitation as above: not exercised against real Bybit testnet
connectivity in this repository's development sessions. The
retry/checkpoint logic itself is unit-tested with an injected failing
`run_fn` (`tests/unit/test_supervisor.py`), and fill recording is proven
against NautilusTrader's real backtest engine
(`tests/integration/test_session_recorder_live.py`) — only the live
network path is unverified here.

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
