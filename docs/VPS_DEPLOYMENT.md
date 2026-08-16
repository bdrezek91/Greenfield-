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
- `research-worker` — the autonomous research factory (`src/research/`),
  one gated cycle per `--interval-hours`. See the dedicated section below.
- `paper-session` — one explicitly-approved strategy on Bybit Demo.
- `microstructure-collector` — public order book/trade tape/liquidations.
- `data-compactor` — daily, atomic compaction of microstructure files.

Each service does one job and can be restarted/scaled independently. None
of the four newer services has a LIVE code path or API credentials capable
of placing a real order - see `docs/LIVE_READINESS_CHECKLIST.md`.

## Autonomous research factory

```bash
# Research worker - runs a bounded, gated research cycle on a schedule.
docker compose up -d research-worker
docker compose logs -f research-worker
docker compose ps research-worker            # health status
docker compose stop research-worker          # graceful (SIGTERM, finishes current cycle)
docker compose restart research-worker

# Paper session - requires PAPER_SYMBOL/PAPER_STRATEGY in .env first (see
# .env.example) - never auto-selected. Set these only after a candidate
# has been promoted via src/research/promotion.py and a human has reviewed it.
docker compose up -d paper-session
docker compose logs -f paper-session
docker compose stop paper-session

# Microstructure collection + daily compaction.
docker compose up -d microstructure-collector
docker compose up -d data-compactor
docker compose logs -f microstructure-collector data-compactor
```

**Status/health**: `docker compose ps` shows each service's healthcheck
state (`healthy`/`unhealthy`/`starting`). `research-worker` and
`paper-session` are marked unhealthy if their heartbeat/checkpoint file
hasn't updated recently (see their `healthcheck` blocks in
`docker-compose.yml`) - `restart: unless-stopped` then restarts the
container automatically.

**Disk-space guard**: `src/research/orchestrator.py:run_cycle` checks free
disk space before doing any work and aborts the cycle (status `ERROR`,
nothing partially written) if fewer than 500MB are free, rather than
failing mid-write.

**Retention**: research cycle reports (`reports/research_cycles/<id>/`)
and the trial ledger/promotion state are never deleted automatically -
retention/archival is an operational decision for whoever runs the VPS,
not something this codebase enforces unilaterally against research
history. Docker's own log rotation is configured per service
(`max-size: 10m`, `max-file: 5`) so container logs don't grow unbounded.

**Backup**: back up the `ai-trading-lab-data` and `ai-trading-lab-reports`
named volumes (or their host bind-mount equivalents) - both are declared
in `docker-compose.yml`'s `volumes:` section and contain everything that
isn't reproducible from git (klines/funding/OI/microstructure data,
`reports/experiments/experiments.jsonl`, `reports/research/trial_ledger.jsonl`,
`reports/research/promotion_state.json`, every past cycle's report bundle).
A plain `docker run --rm -v ai-trading-lab-reports:/from -v $PWD:/to alpine
tar czf /to/reports-backup.tar.gz -C /from .` (same pattern for the data
volume) is sufficient - no database to dump.

**Disaster recovery**: restoring the two volumes from a backup and running
`docker compose up -d` again is sufficient to resume - the trial ledger and
promotion state are plain JSON/JSONL files, not requiring any migration.
`src/research/locking.py:CycleLock` detects and takes over a stale lock
left by a crashed prior worker (checks whether the recorded PID is still
alive) automatically on the next cycle, so a hard container kill mid-cycle
does not permanently wedge `research-worker`.

**Alerts** (see `docs/AUTONOMOUS_RESEARCH_AUDIT.md`'s known limitations for
what's NOT yet wired to an external channel): the pieces that would feed
alerting exist today as observable state, not yet as pushed
notifications - `research-worker`'s healthcheck (stale heartbeat = no
fresh data / a stuck cycle), `microstructure-collector`'s healthcheck (no
fresh Parquet files = a dead feed), each research cycle's `status` field
(`ERROR` = the cycle itself failed to run), and
`src/research/promotion.py`'s `DEGRADED`/`RETIRED` transitions (a paper
candidate degrading). Wiring these into `docker compose ps`/healthcheck
failures or a container-exit-code monitor into an actual Slack/email/push
notification is an infrastructure choice for the specific VPS (e.g.
Docker's own `--health-cmd` exit code plus any standard container
monitoring agent) rather than something this repository should hardcode a
single vendor integration for.

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
export BYBIT_TESTNET_API_KEY=...
export BYBIT_TESTNET_API_SECRET=...
python scripts/paper_trade.py --symbol BTCUSDT --timeframe 1h --strategy trend_following

# --backend demo: Bybit's "Demo Trading" feature for account/order actions,
# reachable from an existing regular bybit.com login (avatar menu -> Demo
# Trading), no separate site registration - use this if testnet.bybit.com
# registration is geo-blocked for you. Generate these while switched into
# Demo Trading mode. ALSO needs a real mainnet BYBIT_API_KEY/SECRET
# ("Tylko do snapshotu" / read-only is enough, cannot place orders or move
# funds) - Bybit's Demo Trading REST only supports private/account
# endpoints, so market-data (public) calls need a plain mainnet client
# instead; see src/execution/paper_node.py's module docstring.
export TRADING_MODE=PAPER
export BYBIT_DEMO_API_KEY=...
export BYBIT_DEMO_API_SECRET=...
export BYBIT_API_KEY=...          # real mainnet, read-only permission is enough
export BYBIT_API_SECRET=...
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
