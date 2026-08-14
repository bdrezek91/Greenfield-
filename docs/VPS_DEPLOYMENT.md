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

`TRADING_MODE` in `.env` controls `RESEARCH` / `BACKTEST` / `PAPER` / `LIVE`.
`LIVE` is disabled by default; enabling it requires an explicit safety
mechanism introduced in a later phase — it is not reachable by simply
setting an environment variable today.

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
