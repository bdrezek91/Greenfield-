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
live-trading execution path exists yet regardless (only `PAPER`, against
Bybit's testnet via `scripts/paper_trade.py`, is implemented).

## Paper trading (Bybit testnet)

```bash
export TRADING_MODE=PAPER
export BYBIT_API_KEY=...       # Bybit TESTNET key - never a mainnet key here
export BYBIT_API_SECRET=...
python scripts/paper_trade.py --symbol BTCUSDT --timeframe 1h --strategy trend_following
```

This runs the exact same `Strategy` class used in backtests
(`src/strategies/`) live against Bybit's testnet, via NautilusTrader's
native Bybit adapter (`src/execution/paper_node.py`) — the Phase 0
architecture decision's payoff: no strategy code changes between backtest
and paper. See `docs/RESEARCH_METHODOLOGY.md` for the expected-vs-actual
fill comparison this mode is meant to produce (latency, slippage, rejected
orders, data issues).

**Known limitation:** this repository's development sessions run under a
network policy that blocks `api.bybit.com`, so live testnet connectivity
has not been exercised end to end in that environment (only construction of
the trading node, without connecting, has been verified — see
`docs/PROJECT_STATUS.md`). Validate connectivity on the actual VPS or a
local machine with unrestricted network access before relying on this.

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
